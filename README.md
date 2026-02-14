<p align="center">
  <img src="https://github.com/hass-energy/amber-express/raw/main/images/logo.png" alt="Amber Express" width="500">
</p>

<p align="center">
  <strong>Faster Amber Electric pricing for Home Assistant and <a href="https://haeo.io/">HAEO</a></strong>
</p>

<p align="center">
  <a href="https://github.com/hass-energy/amber-express/releases"><img src="https://img.shields.io/github/v/release/hass-energy/amber-express?style=flat-square" alt="Release"></a>
  <a href="https://github.com/hass-energy/amber-express/blob/main/LICENSE"><img src="https://img.shields.io/github/license/hass-energy/amber-express?style=flat-square" alt="License"></a>
  <a href="https://github.com/custom-components/hacs"><img src="https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square" alt="HACS"></a>
</p>

---

A Home Assistant custom integration for [Amber Electric](https://www.amber.com.au/) that provides faster real-time electricity pricing with smart polling and WebSocket support.

## Features

- **Simple Setup**: Just like the official integration - enter your API key, select a site, and you're done
- **Smart Polling**: Adapts and learns when confirmed prices typically arrive and polls at those times to fetch latest prices as fast as possible
- **WebSocket Support**: Supports real-time updates via Amber's WebSocket API (alpha feature) as a redundant data source to polling
- **Flexible Pricing**: Choose between AEMO-based pricing (per_kwh) or Amber's predicted pricing (advanced_price_predicted)
- **HAEO Compatible**: Forecast sensors are fully compatible with [HAEO](https://haeo.io/) for energy optimization

## Installation

### HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hass-energy&repository=amber-express&category=integration)

Or manually:

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right and select "Custom repositories"
4. Add this repository URL and select "Integration" as the category
5. Click "Install"
6. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/amber_express` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** > **Devices & Services**
2. Click **Add Integration**
3. Search for "Amber Express"
4. Enter your Amber API token (get one from [Amber Developer Settings](https://app.amber.com.au/developers/))
5. Select your site from the dropdown
6. Optionally configure the integration options

## HAEO Integration

The forecast sensors are designed to work seamlessly with [HAEO](https://haeo.io/). Simply add the forecast sensors to your HAEO Grid element configuration:

```yaml
# Example: Use in HAEO
Import Price: sensor.amber_express_general_forecast
Export Price: sensor.amber_express_feed_in_forecast
```

## Smart Polling

Amber Express learns when confirmed prices typically arrive and schedules its polling at the most likely times.

1. At the start of each 5-minute interval, polls to get the initial estimate price and forecast
2. Tracks when confirmed prices historically arrive and times subsequent polls accordingly
3. Stops polling once confirmed price is received

This adaptive approach typically delivers confirmed prices within seconds of publication.

## WebSocket Support

The integration will (optionally) connect to Amber's WebSocket API for real-time push updates. This is an alpha feature from Amber and cannot be currently relied upon, so it is used in tandem, getting prices from whichever API is faster.

## Comparison

| Feature          | Amber Express            | amber2mqtt                | Amber Electric     |
| ---------------- | ------------------------ | ------------------------- | ------------------ |
| Polling          | Adaptive (learns timing) | Scheduled (you configure) | Fixed 1-minute     |
| Update Speed     | Fastest                  | Fast                      | Slow               |
| Stops on Confirm | Yes                      | Yes                       | No                 |
| WebSocket        | Optional (alpha)         | No                        | No                 |
| Environment      | Native Integration       | Addon + Requires MQTT     | Native Integration |

## Credits

This integration is inspired by:

- [Official Amber Electric Integration](https://www.home-assistant.io/integrations/amberelectric/)
- [amber2mqtt](https://github.com/cabberley/amber2mqtt) by cabberley
- [AmberWebSocket](https://github.com/cabberley/AmberWebSocket) by cabberley

## License

MIT License
