import asyncio

from whaletop.app import WhaletopApp
from whaletop.screens.dialogs import ChoiceScreen
from whaletop.screens.viewers import HelpScreen, InspectScreen, LogScreen


async def settle(pilot, t=0.6):
    await pilot.pause(t)


async def until(pred, timeout=10.0):
    for _ in range(int(timeout / 0.05)):
        if pred():
            return True
        await asyncio.sleep(0.05)
    return pred()


def select(view, key):
    view.table.move_cursor(row=view.table._shown.index(key))


async def test_containers_tab_lists_and_sorts(svc):
    app = WhaletopApp(svc)
    async with app.run_test(size=(160, 40)) as pilot:
        v = app.views["containers"]
        # sorted by name; the compose project groups its containers, standalone ones are plain rows
        assert await until(lambda: v.table._shown == ["bbb222", "p:demo", "ddd444", "eee555", "ccc333", "aaa111"])
        await pilot.press("h")  # hide stopped
        await settle(pilot, 0.2)
        assert v.table._shown == ["bbb222", "p:demo", "ddd444", "aaa111"]
        # live stats arrive from the fake stream
        assert await until(lambda: app.stats.snapshot().get("aaa111") is not None)


async def test_filter(svc):
    app = WhaletopApp(svc)
    async with app.run_test(size=(160, 40)) as pilot:
        v = app.views["containers"]
        assert await until(lambda: len(v.table._shown) == 6)
        await pilot.press("slash", "d", "b", "enter")
        await settle(pilot, 0.2)
        assert v.table._shown == ["bbb222"]
        await pilot.press("slash", "escape")
        await settle(pilot, 0.2)
        assert len(v.table._shown) == 6


async def test_stop_start_and_remove_with_confirm(svc):
    app = WhaletopApp(svc)
    async with app.run_test(size=(160, 40)) as pilot:
        v = app.views["containers"]
        assert await until(lambda: "aaa111" in v.table._shown)
        select(v, "aaa111")
        await pilot.press("s")
        assert await until(lambda: ("stop", "aaa111") in svc.calls)

        select(v, "ccc333")
        await pilot.press("d")
        await settle(pilot, 0.2)
        assert isinstance(app.screen, ChoiceScreen)
        await pilot.press("enter")  # focused button is the destructive one
        assert await until(lambda: ("remove_container", "ccc333", False) in svc.calls)


async def test_escape_cancels_confirm(svc):
    app = WhaletopApp(svc)
    async with app.run_test(size=(160, 40)) as pilot:
        v = app.views["containers"]
        assert await until(lambda: "aaa111" in v.table._shown)
        select(v, "aaa111")
        await pilot.press("d")
        await settle(pilot, 0.2)
        await pilot.press("escape")
        await settle(pilot, 0.2)
        assert not isinstance(app.screen, ChoiceScreen)
        assert not any(c[0] == "remove_container" for c in svc.calls)


async def test_logs_and_inspect_screens(svc):
    app = WhaletopApp(svc)
    async with app.run_test(size=(160, 40)) as pilot:
        v = app.views["containers"]
        assert await until(lambda: "aaa111" in v.table._shown)
        select(v, "aaa111")
        await pilot.press("l")
        assert await until(lambda: isinstance(app.screen, LogScreen) and len(app.screen.lines) == 5)
        await pilot.press("escape")
        await pilot.press("i")
        assert await until(lambda: isinstance(app.screen, InspectScreen))
        assert app.screen.data == {"Kind": "container", "Id": "aaa111"}


async def test_images_volumes_networks(svc):
    app = WhaletopApp(svc)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.press("2")
        iv = app.views["images"]
        assert await until(lambda: len(iv.table._shown) == 3)
        nginx = next(k for k in iv.table._shown if "nginx" in k)
        assert iv.table.by_key[nginx].data["used"] == 3  # web + both demo containers

        await pilot.press("3")
        vv = app.views["volumes"]
        assert await until(lambda: len(vv.table._shown) == 2)
        assert vv.table.by_key["data"].data["users"] == ["db"]
        select(vv, "data")
        await pilot.press("d")  # in use -> refused without a dialog
        await settle(pilot, 0.2)
        assert not isinstance(app.screen, ChoiceScreen)

        await pilot.press("4")
        nv = app.views["networks"]
        assert await until(lambda: len(nv.table._shown) == 2)
        assert len(nv.table.by_key["net-bridge"].data["members"]) == 5
        select(nv, "net-custom")
        await pilot.press("d")
        await settle(pilot, 0.2)
        await pilot.press("enter")
        assert await until(lambda: ("remove_network", "net-custom") in svc.calls)


async def test_cleanup_previews_and_runs(svc):
    from whaletop.screens.cleanup import CleanupScreen

    app = WhaletopApp(svc)
    async with app.run_test(size=(160, 40)) as pilot:
        # containers: the two stopped ones are listed
        v = app.views["containers"]
        assert await until(lambda: len(v.table._shown) == 6)
        await pilot.press("X")
        await settle(pilot, 0.3)
        assert isinstance(app.screen, CleanupScreen)
        [opt] = app.screen.options
        assert sorted(opt.items) == ["demo-cache-1", "old-job"]
        await pilot.press("enter")  # focus starts on Cancel
        await settle(pilot, 0.2)
        assert not isinstance(app.screen, CleanupScreen) and ("prune_containers",) not in svc.calls
        await pilot.press("X")
        await settle(pilot, 0.3)
        await pilot.click("#c-stopped")
        assert await until(lambda: ("prune_containers",) in svc.calls)

        # images: dangling is only the untagged one, "all unused" adds the unused tagged ones
        await pilot.press("2")
        assert await until(lambda: app.views["images"].data is not None)
        await pilot.press("X")
        await settle(pilot, 0.3)
        opts = {o.id: o for o in app.screen.options}
        assert opts["dangling"].items == ["<none> dangling"]
        assert sorted(opts["unused"].items) == ["<none> dangling"]  # nginx and postgres are in use
        await pilot.press("escape")
        await settle(pilot, 0.2)
        assert not any(c[0] == "prune_images" for c in svc.calls)

        # volumes: "data" is used by db, "scratch" is unused
        await pilot.press("3")
        assert await until(lambda: app.views["volumes"].data is not None)
        await pilot.press("X")
        await settle(pilot, 0.3)
        opts = {o.id: o for o in app.screen.options}
        assert opts["all"].items == ["scratch"] and opts["anon"].items == []
        await pilot.press("escape")

        # networks: only the custom one, never bridge
        await pilot.press("4")
        assert await until(lambda: app.views["networks"].data is not None)
        await pilot.press("X")
        await settle(pilot, 0.3)
        assert app.screen.options[0].items == ["custom"]
        await pilot.click("#c-unused")
        assert await until(lambda: ("prune_networks",) in svc.calls)


async def test_compose_group_in_containers_tab(svc):
    app = WhaletopApp(svc)
    async with app.run_test(size=(160, 40)) as pilot:
        v = app.views["containers"]
        assert await until(lambda: "p:demo" in v.table._shown)
        assert v.table.by_key["ddd444"].parent == "p:demo"
        assert v.table.by_key["aaa111"].parent is None
        select(v, "p:demo")
        await pilot.press("enter")  # collapse
        await settle(pilot, 0.2)
        assert "ddd444" not in v.table._shown and "p:demo" in v.table._shown
        await pilot.press("enter")  # expand again
        await settle(pilot, 0.2)
        assert "ddd444" in v.table._shown
        # filtering by a child name keeps its project row visible
        await pilot.press("slash", "c", "a", "c", "h", "e", "enter")
        await settle(pilot, 0.2)
        assert v.table._shown == ["p:demo", "eee555"]
        await pilot.press("slash", "escape")
        await settle(pilot, 0.2)
        select(v, "p:demo")
        # compose file doesn't exist, so project restart falls back to per-container SDK calls
        await pilot.press("r")
        assert await until(lambda: ("restart", "ddd444") in svc.calls and ("restart", "eee555") in svc.calls)
        # and `up` refuses instead of running compose
        await pilot.press("u")
        await settle(pilot, 0.2)
        assert not any(c[0] == "popen" for c in svc.calls)
        # container keys on a project row warn instead of acting
        await pilot.press("e")
        await settle(pilot, 0.2)
        assert not any(c[0] == "exec" for c in svc.calls)


async def test_help_and_tab_cycling(svc):
    app = WhaletopApp(svc)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.press("question_mark")
        await settle(pilot, 0.2)
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        from textual.widgets import TabbedContent
        await pilot.press("right_square_bracket")
        assert app.query_one(TabbedContent).active == "images"
        await pilot.press("left_square_bracket", "left_square_bracket")
        assert app.query_one(TabbedContent).active == "networks"


async def test_images_sorted_by_name_and_stable(svc):
    # two images with identical timestamps, returned in a different order on each call
    svc._images = [
        {"Id": "sha256:b", "RepoTags": ["zeta:1"], "Size": 1, "Created": 5},
        {"Id": "sha256:a", "RepoTags": ["alpha:1"], "Size": 1, "Created": 5},
        {"Id": "sha256:c", "RepoTags": None, "RepoDigests": [], "Size": 1, "Created": 5},
    ]
    app = WhaletopApp(svc)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.press("2")
        iv = app.views["images"]
        assert await until(lambda: len(iv.table._shown) == 3)
        expected = ["sha256:a|alpha:1", "sha256:b|zeta:1", "sha256:c|"]  # <none> last
        assert iv.table._shown == expected
        svc._images.reverse()
        iv.reload()
        await settle(pilot, 0.5)
        assert iv.table._shown == expected
        # sorting by CREATED (all tied) is still deterministic across reloads
        iv.table.set_sort("created")
        first = list(iv.table._shown)
        svc._images.reverse()
        iv.reload()
        await settle(pilot, 0.5)
        assert iv.table._shown == first
