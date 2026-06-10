import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        page.on("console", lambda msg: print(f"Browser console: {msg.text}"))
        page.on("pageerror", lambda err: print(f"Browser error: {err}"))
        
        try:
            print("Opening page...")
            await page.goto("http://127.0.0.1:5000/", timeout=60000)
            await page.wait_for_selector(".movie-card", timeout=30000)
            
            print("Creating user 'test'...")
            await page.fill("#newUserInput", "test")
            await page.click("button[onclick='addUser()']")
            await page.wait_for_selector(".movie-card", timeout=30000)
            
            print("Saving screenshot 1...")
            await page.screenshot(path="test_run_1_initial.png")
            
            print("Simulating likes and skips...")
            for i in range(10):
                await page.wait_for_timeout(2000)
                like_buttons = await page.query_selector_all(".movie-card:not(.card-disabled) .btn-like")
                skip_buttons = await page.query_selector_all(".movie-card:not(.card-disabled) .btn-dislike")
                
                if like_buttons:
                    if i % 3 == 0 and skip_buttons:
                        await skip_buttons[0].click()
                    else:
                        await like_buttons[0].click()
                else:
                    break
                        
            # Wait for Top 3 modal
            print("Waiting for Top 3 modal...")
            await page.wait_for_selector("#top3Modal", state="visible", timeout=30000)
            await page.wait_for_timeout(2000)
            
            print("Saving screenshot 2...")
            await page.screenshot(path="test_run_2_top3.png")
            
            print("Closing Top 3 modal...")
            await page.click("#top3Modal button.btn-like")
            await page.wait_for_selector("#top3Modal", state="hidden", timeout=30000)
            await page.wait_for_timeout(2000)
            
            print("Saving screenshot 3...")
            await page.screenshot(path="test_run_3_exploration.png")
            
        except Exception as e:
            print(f"Error occurred: {e}")
            await page.screenshot(path="error.png")
            
        await browser.close()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
