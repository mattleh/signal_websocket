# Signal Messenger WebSocket & REST for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![HA Version](https://img.shields.io/badge/Home%20Assistant-2025.1+-blue.svg)

A high-performance Home Assistant integration to receive Signal messages in real-time. This integration bridges Home Assistant with the [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api).

## ✨ Key Features

* **Auto-Detection:** Automatically uses WebSocket for real-time push when available, falls back to REST polling.
* **Profile Management:** Update your Signal name, 'About' status, and avatar (via URL or local path) directly from the integration options.
* **Smart Filtering:** Automatically ignores "Typing..." indicators and empty delivery receipts to prevent "New Event" spam.
* **Privacy Controls:** Opt-in monitoring for group messages to prevent unwanted event spam and ensure privacy.
* **Assist Integration:** Native bridge to Home Assistant Assist. Control your home by texting or sending voice messages to your Signal account.
* **Voice Transcription:** Automatically transcribes Signal voice messages (M4A/AAC) using Home Assistant's STT engines for processing via Assist.
* **REST Fallback:** Robust REST polling mode with configurable intervals when WebSocket is unavailable.
* **Multi-Message Batching:** In REST mode, all messages received during a poll are captured, with the sensor state updating to the latest message.
* **Event-Driven:** Fires a `signal_received` event for every message, making it perfect for complex automations.
* **Automatic Reconnect:** Built-in exponential backoff and heartbeat pings to keep the connection alive.
* **Comprehensive API Coverage:** Services for sending messages, managing groups, contacts, and more.
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

### ⚙️ Options & Configuration
After the initial setup, you can click **Configure** on the integration card to access a navigation menu:

#### 1. General Settings
* **Polling Interval:** Set the fallback polling frequency (1-3600s).
* **Selected Contacts/Groups:** Choose which Signal entities should be created as sensors in HA.
#### 2. Update Profile
* Update your Signal display name, 'About' status, and Profile Avatar (supports local file paths or external URLs).
#### 3. Assist Settings
* **Enable Assist:** Toggle the bridge between Signal and Home Assistant Assist.
* **Receive Groups:** Opt-in to monitor incoming messages from specific groups (enables events and automations). Groups must be in this list before they can be authorized for Assist.
* **Authorized Contacts/Groups:** Specifically authorize who can trigger Assist commands (subset of monitored groups).
* **Voice Messages (STT):** Enable automatic transcription of incoming voice messages.

---

## 🤖 Assist Integration

When **Assist Integration** is enabled, authorized users can send messages to the Signal account to trigger Assist commands (e.g., "Turn on the kitchen light"). 

**Privacy Note:** Group messages are only monitored if the group is explicitly added to the **Receive Groups** list. This prevents unwanted event spam from groups where HA is just a member for outbound notifications. Groups in **Receive Groups** can fire `signal_received` events for automations, but only groups in **Authorized Contacts/Groups** will forward messages to Assist.

If **Voice message transcription** is enabled, you can also send Signal voice notes. The integration will transcode the audio using FFmpeg, transcribe it via your default Assist STT engine, and process the resulting text.

---

## 🤖 Services

The integration provides comprehensive services to interact with Signal:

### Messaging
- **send_message**: Send text messages or attachments to individuals or groups.
- **notify**: Standard Home Assistant Notify entity for easy automation usage.

### Groups
- **create_group**: Create new Signal groups with custom permissions and disappearing message timers.
- **manage_group_membership**: Unified service to add/remove members or promote/demote administrators.(broken maybe signal-cli problem)
- **update_group**: Update group name, description, and settings. untested
- **delete_group**: Permanently delete groups. (working partly)

### Contacts
- **sync_contacts**: Sync local contacts to linked devices. untested
- **update_contact**: Update contact names and information. untested
- **remove_contact**: Remove a contact from the local list. untested

## � Supported API Endpoints

- **`GET /v1/receive/{number}`**: Receive incoming Signal messages via WebSocket or REST polling.
- **`POST /v2/send`**: Send messages with attachments, quotes, replies, stickers, and rich text styling.
- **`GET /v1/groups/{number}`**: List Signal groups for the configured account.
- **`POST /v1/groups/{number}`**: Create a new Signal group. (not testet)
- **`PUT /v1/groups/{number}/{groupid}`**: Update group metadata and permissions.
- **`DELETE /v1/groups/{number}/{groupid}`**: Delete a group.
- **`POST /v1/groups/{number}/{groupid}/members`**: Add members to a group.
- **`DELETE /v1/groups/{number}/{groupid}/members`**: Remove members from a group.
- **`POST /v1/groups/{number}/{groupid}/admins`**: Promote members to admin.
- **`DELETE /v1/groups/{number}/{groupid}/admins`**: Demote admins to members.
- **`GET /v1/contacts/{number}`**: List contacts for the configured account.
- **`PUT /v1/contacts/{number}`**: Update or add a contact.
- **`POST /v1/contacts/{number}/sync`**: Sync contacts to linked devices.
- **`PUT /v1/profiles/{number}`**: Update profile name, about, and avatar.

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
