# Signal Messenger WebSocket & REST for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![HA Version](https://img.shields.io/badge/Home%20Assistant-2025.1+-blue.svg)

A high-performance Home Assistant integration to receive Signal messages in real-time. This integration bridges Home Assistant with the [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api).

## ✨ Key Features

* **Real-time Push:** Uses WebSockets for instant message delivery without polling delay.
* **Smart Filtering:** Automatically ignores "Typing..." indicators and empty delivery receipts to prevent "New Event" spam.
* **REST Fallback:** Includes a robust REST polling mode with configurable intervals.
* **Multi-Message Batching:** In REST mode, all messages received during a poll are captured in attributes.
* **Event-Driven:** Fires a `signal_received` event for every message, making it perfect for complex automations.
* **Automatic Reconnect:** Built-in exponential backoff and heartbeat pings to keep the connection alive.

## 🚀 Installation

### 1. Prerequisites
You need a running instance of `signal-cli-rest-api`. 
**Note:** Ensure the container is running in `json-rpc` mode.

### 2. HACS (Recommended)
1. Open **HACS** in Home Assistant.
2. Click the three dots in the top right and select **Custom repositories**.
3. Add your GitHub URL and select **Integration** as the category.
4. Click **Download**.

### 3. Manual
Copy the `custom_components/signal_websocket` folder into your Home Assistant `custom_components` directory and restart HA.

## ⚙️ Configuration

Go to **Settings > Devices & Services > Add Integration** and search for **Signal Messenger WebSocket**.

| Option | Description |
| :--- | :--- |
| **Host** | IP or Hostname of your Signal API container. |
| **Port** | API Port (Default: 8080). |
| **Number** | Your registered Signal number (e.g., +49...). |
| **Connection Type** | Choose `WebSocket` (instant) or `REST` (polling). |

## 🤖 Automation Example

Use the `signal_received` event to trigger actions. Here is an example of a simple notification bot:

```yaml
alias: "Signal: Respond to lights command"
trigger:
  - platform: event
    event_type: signal_received
condition:
  - condition: template
    value_template: "{{ 'turn off lights' in trigger.event.data.envelope.dataMessage.message | lower }}"
action:
  - action: light.turn_off
    target:
      entity_id: all
