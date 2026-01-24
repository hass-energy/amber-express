<p align="center">
  <img src="images/logo.png" alt="Amber Express" width="400">
</p>

<p align="center">
  <strong>Real-time Amber Electric pricing for Home Assistant</strong>
</p>

<p align="center">
  <a href="https://github.com/hass-energy/amber-express/releases"><img src="https://img.shields.io/github/v/release/hass-energy/amber-express?style=flat-square" alt="Release"></a>
  <a href="https://github.com/hass-energy/amber-express/blob/main/LICENSE"><img src="https://img.shields.io/github/license/hass-energy/amber-express?style=flat-square" alt="License"></a>
  <a href="https://github.com/custom-components/hacs"><img src="https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square" alt="HACS"></a>
</p>

---

A Home Assistant custom integration for [Amber Electric](https://www.amber.com.au/) that provides real-time electricity pricing with smart polling and WebSocket support.

## Features

- **Simple Setup**: Just like the official integration - enter your API key, select a site, and you're done
- **Smart Polling**: Intelligent polling inspired by [amber2mqtt](https://github.com/cabberley/amber2mqtt) - polls frequently at the start of each 5-minute interval and stops once a confirmed price is received
- **WebSocket Support**: Optional real-time updates via Amber's WebSocket API (alpha feature) with automatic fallback to polling
- **HAEO Compatible**: Forecast sensors are fully compatible with [HAEO](https://haeo.io/) for energy optimization
- **Flexible Pricing**: Choose between AEMO-based pricing (per_kwh) or Amber's predicted pricing (advanced_price_predicted)

## Installation

### HACS (Recommended)

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

### Options

| Option          | Description                                             | Default |
| --------------- | ------------------------------------------------------- | ------- |
| Pricing Mode    | AEMO (per_kwh with tariffs) or APP (Amber's prediction) | AEMO    |
| General Channel | Enable general consumption sensors                      | On      |
| Feed-in Channel | Enable solar feed-in sensors                            | On      |
| Controlled Load | Enable controlled load sensors                          | Off     |
| WebSocket       | Enable real-time WebSocket updates                      | On      |

## Sensors

### Per Channel (General, Feed-in, Controlled Load)

- **Price**: Current electricity price in $/kWh
- **Forecast**: HAEO-compatible forecast sensor with `forecasts` attribute
- **Price Descriptor**: Current price level (extremely_low, very_low, low, neutral, high, spike)

### Global

- **Renewables**: Current percentage of renewable energy in the grid
- **Price Spike**: Binary sensor indicating if there's a price spike

## HAEO Integration

The forecast sensors are designed to work seamlessly with [HAEO](https://haeo.io/). Simply add the forecast sensors to your HAEO Grid element configuration:

```yaml
# Example: Use in HAEO
Import Price: sensor.amber_express_general_forecast
Export Price: sensor.amber_express_feed_in_forecast
```

The `forecasts` attribute contains data in the format HAEO expects:

```yaml
forecasts:
  - start_time: "2025-01-24T14:00:00+10:00"
    per_kwh: 0.28
  - start_time: "2025-01-24T14:30:00+10:00"
    per_kwh: 0.32
```

## Smart Polling

Unlike the official integration which polls every minute, Amber Express uses intelligent polling:

1. At the start of each 5-minute interval, polling is frequent (every few seconds)
2. Once a confirmed (non-estimate) price is received, polling stops
3. When a new interval starts, the cycle repeats

This approach minimizes API calls while ensuring you get prices as fast as possible.

## WebSocket Support

The integration can optionally connect to Amber's WebSocket API for real-time push updates. This is an alpha feature from Amber and may be slower or unavailable at times. When enabled:

- WebSocket provides instant updates when prices change
- Polling continues as a backup
- The integration uses whichever source provides data first

## Comparison

| Feature         | Official       | amber2mqtt     | Amber Express |
| --------------- | -------------- | -------------- | ------------- |
| Setup           | Simple         | Complex (MQTT) | Simple              |
| Polling         | 1 minute fixed | Smart cron     | Smart cron          |
| WebSocket       | No             | Separate addon | Integrated          |
| HAEO Compatible | Yes            | Via MQTT       | Yes                 |
| Pricing Options | per_kwh only   | Both           | Both                |

## Credits

This integration is inspired by:

- [Official Amber Electric Integration](https://www.home-assistant.io/integrations/amberelectric/)
- [amber2mqtt](https://github.com/cabberley/amber2mqtt) by cabberley
- [AmberWebSocket](https://github.com/cabberley/AmberWebSocket) by cabberley

## License

MIT License
