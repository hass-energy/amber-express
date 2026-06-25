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
  <a href="https://buymeacoffee.com/haeo.io"><img src="https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow.svg?style=flat-square" alt="Buy Me A Coffee"></a>
</p>

---

A Home Assistant custom integration for [Amber Electric](https://www.amber.com.au/) that provides faster real-time electricity pricing with smart polling and WebSocket support.

## Features

- **Simple Setup**: Just like the official integration - enter your API key, select a site, and you're done
- **Smart Polling**: Adapts and learns when confirmed prices typically arrive and polls at those times to fetch latest prices as fast as possible
- **Forecasting**: Provides price forecasts for both import and feed-in channels for automations and optimizers
- **Flexible Pricing**: Choose between AEMO-based pricing (per_kwh) or Amber's predicted pricing (advanced_price_predicted)
- **Waits for Confirmation**: Holds previous prices until confirmed values arrive, with configurable timeout control
- **Demand Window Pricing**: Optionally add a surcharge during demand windows for optimization-focused automations
- **WebSocket Support**: Supports real-time updates via Amber's WebSocket API (alpha feature) as a redundant data source to polling
- **HAEO Compatible**: Forecast sensors are fully compatible with [HAEO](https://haeo.io/) for energy optimization

## Screenshots

| Sensors                                                                                                                        | Diagnostics                                                                                                                            |
| ------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| <img src="https://github.com/hass-energy/amber-express/raw/main/images/sensors.png" alt="Amber Express sensors" width="317px"> | <img src="https://github.com/hass-energy/amber-express/raw/main/images/diagnostics.png" alt="Amber Express diagnostics" width="317px"> |

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
5. Select your site
6. Optionally configure the integration options

## Options

Amber Express supports the following per-site options:

- **Site name**: Display name used for the Home Assistant device and entities
- **Pricing mode**: Choose the price field used by sensors
  - `per_kwh`: AEMO-based pricing (this is what the Amber App displays to users)
  - `advanced_price_predicted`: Amber advanced predicted pricing (this is what Amber SmartShift uses, and recommended for optimizers)
- **Enable WebSocket**: Enables Amber WebSocket updates as a secondary real-time data source
- **Wait for confirmed prices**: Enabled by default; holds previous interval price until confirmation
- **Confirmation timeout (seconds)**: Maximum wait before publishing falling back to estimate price
- **Forecast intervals**: Number of future intervals returned by forecast sensors
- **Demand Window Price ($/kWh)**: Adds a configurable surcharge to general channel prices during demand windows

Adding a demand window price helps optimizers such as [HAEO](https://haeo.io/) avoid importing during the demand window.

## Pricing Modes

There are two pricing modes available that Amber provide, AEMO and Advanced Price Predicted (APP). For the current interval, both pricing modes report the same price as this the real confirmed cost. However, the pricing modes will changes the **forecast** method used for upcoming future intervals.

### AEMO

- This matches the price forecasts shown in the official Amber app
- Forecasts upcoming prices from AEMO's wholesale prices
- These forecasts are often aggressively wrong, predicting price spikes that will last for hours

### Advanced Price (default)

- Amber's own prediction of upcoming prices, built to be more realistic than AEMO
- Despite the Amber app displaying AEMO prices, Amber's SmartShift uses this forecast instead
- Strongly recommended for optimizers such as [HAEO](https://haeo.io/), and the default mode in Amber Express

## HAEO Integration

The forecast sensors are designed to work seamlessly with [HAEO](https://haeo.io/). Simply add the forecast sensors to your HAEO Grid element configuration:

```yaml
# Example: Use in HAEO
Import Price: sensor.amber_express_home_general_price
Export Price: sensor.amber_express_home_feed_in_price
```

## Smart Polling

Each interval opens with an _estimate_ price, then Amber publishes the _confirmed_ price some 10s of seconds later. Smart polling exists to catch that confirmed price as fast as possible without exhausting the API rate limit, so rather than poll on a fixed schedule it learns _when_ confirmed prices tend to arrive and aims to focus the majority of its polling quota around that time.

1. **Observe**: Each time a confirmed price arrives, the integration records the window between the last poll that still saw an estimate and the first poll that saw the confirmed value. The most recent 100 of these observations are kept and persisted across restarts.
2. **Learn**: Those observations are combined into a probability distribution of when confirmation happens across the interval.
3. **Aim**: Given a budget of how many polls it can afford, it concentrates them around the times confirmation is most likely rather than spreading them evenly. As time passes with no confirmed price, it re-targets the remaining likely window.
4. **Stop**: The moment a confirmed price arrives, polling pauses until the next interval.

The poll budget is derived from the API rate limit and recalculated after every response, so the schedule tightens or loosens as quota allows. Polls are also reserved for the interval boundary and for the moment the rate limit resets. In practice this adaptive approach delivers confirmed prices within seconds of publication.

There are two main diagnostic sensors that shows the current state of polling:

1. **Confirmation Delay**: This sensor represents how long it took to receive a confirmed price from the start of an interval. This includes the delay Amber itself has in getting a confirmed price to then pass on.
2. **Confirmation Lag**: This sensor represents the maximum amount of added delay the act of polling may have caused. It is the time between the last unconfirmed poll and the confirmed poll. The goal is to get this as close to zero as possible with smarter polling.

Here is a video of the algorithm adjusting its polling schedule (red dots) as confirmed prices arrived.

https://github.com/user-attachments/assets/e42414fd-526f-456c-a503-3e6751baedf7

## Forecasting

Amber Express includes forecast attributes for both import and feed-in channels.

- Forecast length is configurable using the **Forecast intervals** option
- Forecast sensors update with each polling cycle and can be consumed directly by automations
- Forecast entities are designed to integrate easily with optimizers such as [HAEO](https://haeo.io/)

## Entity Attributes

Each entity exposes additional state attributes alongside its main value. This is where pricing forecasts are available.

### Price sensors (`general`, `feed_in`, `controlled_load`)

| Attribute            | Type     | Description                                                        |
| -------------------- | -------- | ------------------------------------------------------------------ |
| `start_time`         | datetime | Current interval start in local time (minute precision)            |
| `end_time`           | datetime | Current interval end in local time (minute precision)              |
| `estimate`           | boolean  | Whether the current price is an estimate (not yet confirmed)       |
| `descriptor`         | string   | Amber's price descriptor (e.g. `low`, `high`, `spike`)             |
| `data_source`        | string   | Where the price came from, either `polling` or `websocket`         |
| `interpolation_mode` | string   | Always `previous`; describes how to interpolate the forecast curve |
| `forecast`           | list     | Simple `{ time, value }` points for automations and optimizers     |
| `detailedForecast`   | list     | Full raw forecast intervals (ignored by HA recorder)               |

### `site` sensor (diagnostic)

| Attribute         | Type    | Description                                          |
| ----------------- | ------- | ---------------------------------------------------- |
| `id`              | string  | Amber site identifier                                |
| `nmi`             | string  | National Metering Identifier                         |
| `network`         | string  | Distribution network name                            |
| `status`          | string  | Site status (e.g. `active`)                          |
| `interval_length` | integer | Pricing interval length in minutes                   |
| `channels`        | list    | `{ identifier, type, tariff }` per available channel |

### `api_status` sensor (diagnostic)

| Attribute                   | Type     | Description                                    |
| --------------------------- | -------- | ---------------------------------------------- |
| `status_code`               | integer  | Most recent HTTP status code from the API      |
| `rate_limit_quota`          | integer  | Maximum requests allowed in the window         |
| `rate_limit_remaining`      | integer  | Requests remaining in the current window       |
| `rate_limit_reset_at`       | datetime | When the rate-limit quota resets               |
| `rate_limit_window_seconds` | integer  | Rate-limit window size in seconds              |
| `rate_limit_policy`         | string   | Raw rate-limit policy string (e.g. `50;w=300`) |

### `next_poll` sensor (diagnostic)

| Attribute       | Type    | Description                                        |
| --------------- | ------- | -------------------------------------------------- |
| `poll_schedule` | list    | Scheduled poll offsets (seconds into the interval) |
| `poll_count`    | integer | Total polls planned for this interval              |

### `forecast_horizon` sensor (diagnostic)

| Attribute      | Type     | Description                                  |
| -------------- | -------- | -------------------------------------------- |
| `forecast_end` | datetime | Timestamp of the furthest available forecast |

## WebSocket Support

The integration will (optionally) connect to Amber's WebSocket API for real-time push updates. This is an alpha feature from Amber and cannot be currently relied upon, so it is used in tandem, getting prices from whichever API is faster.

## Comparison

| Feature           | Amber Express            | amber2mqtt                | Amber Electric     |
| ----------------- | ------------------------ | ------------------------- | ------------------ |
| Polling           | Adaptive (learns timing) | Scheduled (you configure) | Fixed 1-minute     |
| Update Speed      | Fastest                  | Fast                      | Slow               |
| Waits for Confirm | Configurable             | Always                    | No                 |
| WebSocket         | Optional (alpha)         | No                        | No                 |
| Environment       | Native Integration       | Addon + Requires MQTT     | Native Integration |

## Credits

This integration is inspired by:

- [Official Amber Electric Integration](https://www.home-assistant.io/integrations/amberelectric/)
- [amber2mqtt](https://github.com/cabberley/amber2mqtt) by cabberley
- [AmberWebSocket](https://github.com/cabberley/AmberWebSocket) by cabberley

## License

MIT License
