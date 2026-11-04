import asyncio, sys
from playwright.async_api import async_playwright
OUT = sys.argv[2]
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome")
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark", device_scale_factor=2, locale="de-DE", timezone_id="Europe/Berlin")
        page = await ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        await page.goto(sys.argv[1] + "/")
        await page.wait_for_timeout(1500)
        vis = lambda s: page.locator(s).is_visible()
        print("1 idle: start sichtbar", await vis("#c-start"), "| stop", await vis("#c-stop"))
        await page.screenshot(path=f"{OUT}/ctl_idle.png")
        await page.click("#c-start")            # kurzer Tipp
        await page.wait_for_timeout(1500)
        print("2 nach kurzem Tipp, Status:", await page.locator("#d-status").inner_text())
        box = await page.locator("#c-start").bounding_box()
        await page.mouse.move(box["x"] + 50, box["y"] + 20)
        await page.mouse.down(); await page.wait_for_timeout(1000); await page.mouse.up()
        await page.wait_for_timeout(5000)
        print("3 nach Halten:", await page.locator("#d-status").inner_text(), "| tempo-reihe", await vis("#ctl-speed"), "| pause", await vis("#c-pause"))
        for _ in range(3):
            await page.click("[data-step='0.2']")
        print("4 Ziel nach 3x +:", await page.locator("#ctl-target").inner_text())
        await page.wait_for_timeout(4000)
        await page.screenshot(path=f"{OUT}/ctl_running.png")
        await page.click("[data-preset='5']")
        await page.wait_for_timeout(3000)
        await page.click("#c-pause")
        await page.wait_for_timeout(2500)
        print("5 nach Pause:", await page.locator("#d-status").inner_text(), "| knopf:", await page.locator("#c-start .lbl").inner_text())
        await page.screenshot(path=f"{OUT}/ctl_paused.png")
        await page.click("#c-stop")
        await page.wait_for_timeout(2500)
        print("6 nach Stopp:", await page.locator("#d-status").inner_text())
        print("JS-Fehler:", errs)
        await b.close()
asyncio.run(main())
