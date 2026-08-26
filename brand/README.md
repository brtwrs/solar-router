# Brand images

`icon.svg` is the source. The PNGs that ship with the integration live in
`custom_components/solar_router/brand/` and are rendered from it:

```bash
chrome --headless --default-background-color=00000000 \
  --screenshot=icon.png --window-size=256,256 wrapper.html   # and 512 for icon@2x.png
```

Home Assistant 2026.3+ picks these up locally; no PR to `home-assistant/brands`
is needed. Requirements: square, 256x256 and 512x512, PNG with transparency,
trimmed to minimal empty space on the edges.
