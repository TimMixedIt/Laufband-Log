import asyncio
import sys

from playwright.async_api import async_playwright

BASE = sys.argv[1]
OUT = sys.argv[2]
SHOTS = [
    ("overview_mobile_dark", "", 390, 844, "dark", True),
    ("detail_mobile_dark", "#/w/13", 390, 844, "dark", True),
    ("detail_lost_desktop_dark", "#/w/12", 900, 900, "dark", True),
    ("overview_desktop_light", "", 900, 900, "light", True),
    ("detail_pause_mobile_light", "#/w/10", 390, 844, "light", True),
]


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome")
        for name, h, w, ht, scheme, full in SHOTS:
            ctx = await b.new_context(viewport={"width": w, "height": ht}, color_scheme=scheme,
                                      device_scale_factor=2, locale="de-DE",
                                      timezone_id="Europe/Berlin")
            page = await ctx.new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(BASE + "/" + h)
            await page.wait_for_timeout(900)
            if "detail" in name:
                box = await page.locator("#ch-speed").bounding_box()
                await page.mouse.move(box["x"] + box["width"] * 0.62, box["y"] + 60)
                await page.wait_for_timeout(200)
            await page.screenshot(path=f"{OUT}/{name}.png", full_page=full)
            print(name, "errors:", errors)
            await ctx.close()
        await b.close()

asyncio.run(main())
