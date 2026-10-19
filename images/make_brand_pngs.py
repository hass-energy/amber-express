#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "playwright>=1.40.0",
# ]
# ///
# ruff: noqa: T201
"""Render the SVG branding into the integration's local brand PNGs."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright  # type: ignore[import-not-found]


async def render_svg_to_png(
    svg_path: Path,
    output_path: Path,
    width: int,
    height: int,
) -> None:
    """Render an SVG file to PNG at specified dimensions.

    Args:
        svg_path: Path to the source SVG file
        output_path: Path where the PNG will be saved
        width: Width of the output PNG in pixels
        height: Height of the output PNG in pixels

    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()

        context = await browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
        )
        page = await context.new_page()

        # Read the SVG content
        svg_content = svg_path.read_text(encoding="utf-8")  # noqa: ASYNC240

        # Create HTML that properly scales the SVG
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                * {{
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }}
                html, body {{
                    width: {width}px;
                    height: {height}px;
                    overflow: hidden;
                }}
                svg {{
                    display: block;
                    width: {width}px;
                    height: {height}px;
                }}
            </style>
        </head>
        <body>
            {svg_content}
        </body>
        </html>
        """

        await page.set_content(html)
        await page.wait_for_load_state("networkidle")

        # Take screenshot with transparent background
        await page.screenshot(path=str(output_path), type="png", omit_background=True)

        await browser.close()
        print(f"Created {output_path.name}")


async def main() -> None:
    """Generate the integration's local brand PNGs."""
    images_dir = Path(__file__).parent
    brand_dir = images_dir.parent / "custom_components" / "amber_express" / "brand"

    icon_svg = images_dir / "icon.svg"
    logo_svg = images_dir / "logo.svg"

    await render_svg_to_png(icon_svg, brand_dir / "icon.png", 256, 256)
    await render_svg_to_png(icon_svg, brand_dir / "icon@2x.png", 512, 512)
    await render_svg_to_png(logo_svg, brand_dir / "logo.png", 1400, 128)
    await render_svg_to_png(logo_svg, brand_dir / "logo@2x.png", 2800, 256)

    print(f"\n✅ Brand files saved to: {brand_dir}")


if __name__ == "__main__":
    asyncio.run(main())
