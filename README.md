# Signal Messenger WebSocket & REST for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![HA Version](https://img.shields.io/badge/Home%20Assistant-2025.1+-blue.svg)

A high-performance Home Assistant integration to receive Signal messages in real-time. This integration bridges Home Assistant with the [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api).

## ✨ Key Features

* **Auto-Detection:** Automatically uses WebSocket for real-time push when available, falls back to REST polling.
* **Smart Filtering:** Automatically ignores "Typing..." indicators and empty delivery receipts to prevent "New Event" spam.
* **Assist Integration:** Native bridge to Home Assistant Assist. Control your home by texting or sending voice messages to your Signal account.
* **Voice Transcription:** Automatically transcribes Signal voice messages (M4A/AAC) using Home Assistant's STT engines for processing via Assist.
* **REST Fallback:** Robust REST polling mode with configurable intervals when WebSocket is unavailable.
* **Multi-Message Batching:** In REST mode, all messages received during a poll are captured, with the sensor state updating to the latest message.
* **Event-Driven:** Fires a `signal_received` event for every message, making it perfect for complex automations.
* **Automatic Reconnect:** Built-in exponential backoff and heartbeat pings to keep the connection alive.
* **Comprehensive API Coverage:** Services for sending messages, managing groups, contacts, reactions, receipts, and more.
* **Data Sensors:** Additional sensors for groups and contacts overview.

## 🚀 Installation

### 1. Prerequisites
You need a running instance of `signal-cli-rest-api`. 
**Note:** Ensure the container is running in `json-rpc` mode.

### 2. HACS (Recommended)
1. Open **HACS** in Home Assistant.
2. Click the three dots in the top right and select **Custom repositories**.
3. Add [GitHub](https://github.com/mattleh/signal_websocket) URL and select **Integration** as the category.
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

The integration automatically detects and uses WebSocket for real-time messages when available, otherwise falls back to REST polling.

### ⚙️ Options & Assist Authorization
After the initial setup, you can click **Configure** on the integration card to access advanced settings:

| Option | Description |
| :--- | :--- |
| **Polling Interval** | Set the fallback polling frequency (1-3600s). |
| **Selected Contacts/Groups** | Choose which Signal entities should be created as sensors in HA. |
| **Enable Assist** | Toggle the bridge between Signal and Home Assistant Assist. |
| **Authorized Contacts/Groups** | For security, specifically authorize who can trigger Assist commands. |
| **Voice Messages (STT)** | Enable automatic transcription of incoming voice messages. |

---

## 🤖 Assist Integration

When **Assist Integration** is enabled, authorized users can send messages to the Signal account to trigger Assist commands (e.g., "Turn on the kitchen light"). 

If **Voice message transcription** is enabled, you can also send Signal voice notes. The integration will transcode the audio using FFmpeg, transcribe it via your default Assist STT engine, and process the resulting text.

---

## 🤖 Services

The integration provides comprehensive services to interact with Signal:

### Messaging
- **send_message**: Send text messages or attachments to individuals or groups.
- **remote_delete**: Delete sent messages remotely. (not testet)
- **set_typing_indicator**: Show/hide typing indicator. (not testet) not working?

### Groups
- **create_group**: Create new Signal groups. (not testet)
- **add_group_members** / **remove_group_members**: Manage group membership. (not testet)
- **update_group**: Update group name or description. (not testet)
- **delete_group**: Delete groups. (not testet)

### Contacts & Profile
- **sync_contacts**: Sync contacts to linked devices. (not testet)
- **update_contact**: Update contact information. (not testet)
- **remove_contact**: Remove a contact from the local list. (not testet)
- **update_profile**: Update your Signal profile. (not testet)
- **register_number**: Register a new Signal number. (not testet)
- **verify_number**: Verify a registered number with SMS token. (not testet)

## � Supported API Endpoints

- **`GET /v1/receive/{number}`**: Receive incoming Signal messages via WebSocket or REST polling.
- **`POST /v2/send`**: Send messages with attachments, quotes, replies, stickers, and rich text styling.
- **`DELETE /v1/remote-delete/{number}`**: Delete a sent message remotely. (not testet)
- **`GET /v1/groups/{number}`**: List Signal groups for the configured account.
- **`POST /v1/groups/{number}`**: Create a new Signal group. (not testet)
- **`PUT /v1/groups/{number}/{groupid}`**: Update group metadata. (not testet)
- **`DELETE /v1/groups/{number}/{groupid}`**: Delete a group. (not testet)
- **`POST /v1/groups/{number}/{groupid}/members`**: Add members to a group. (not testet)
- **`DELETE /v1/groups/{number}/{groupid}/members`**: Remove members from a group. (not testet)
- **`GET /v1/contacts/{number}`**: List contacts for the configured account.
- **`PUT /v1/contacts/{number}`**: Update or add a contact. (not testet)
- **`POST /v1/contacts/{number}/sync`**: Sync contacts to linked devices. (not testet)
- **`POST /v1/register/{number}`**: Register a new Signal number. (not testet)
- **`POST /v1/register/{number}/verify/{token}`**: Verify a registered number. (not testet)

## �📊 Sensors

- **Signal Messages**: Shows latest received message (WebSocket or polling).
- **Signal Groups**: Lists all your Signal groups with member counts.
- **Signal Contacts**: Lists all your Signal contacts.

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
