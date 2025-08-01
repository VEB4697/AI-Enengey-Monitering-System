// --- Libraries ---
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <DNSServer.h>
#include <EEPROM.h>
#include <ArduinoJson.h>     // For JSON parsing/serialization
#include <ESP8266HTTPClient.h>     // For making HTTP requests
#include <PZEM004Tv30.h>     // Library for PZEM-004T v30
#include <SoftwareSerial.h>  // For connecting PZEM to ESP8266 using SoftwareSerial

// --- Configuration Struct (Stored in EEPROM) ---
struct DeviceConfig {
  char wifi_ssid[64];
  char wifi_password[64];
  char device_api_key[37]; // UUID string (36 chars) + null terminator
  bool configured;
  char device_type[32]; // Added to specify device type, e.g., "power_monitor"
};

DeviceConfig deviceConfig;

// --- Web Server for SoftAP Mode ---
const byte DNS_PORT = 53;
DNSServer dnsServer;
ESP8266WebServer webServer(80);

// HTML for the config portal (simplified, for actual use, load from data/index.html)
const char PROGMEM CONFIG_PORTAL_HTML[] = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <title>IoT Device Setup</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; background-color: #f4f7f6; color: #333; }
    .container { max-width: 450px; margin: auto; padding: 30px; border: 1px solid #e0e0e0; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); background-color: #ffffff; }
    h2 { color: #2c3e50; margin-bottom: 25px; }
    .key-display { background-color: #ecf0f1; padding: 12px; border-radius: 5px; margin-bottom: 25px; border: 1px dashed #bdc3c7; font-size: 1.1em; word-break: break-all; }
    label { display: block; text-align: left; margin-bottom: 5px; font-weight: bold; color: #555; }
    input[type="text"], input[type="password"] { width: calc(100% - 22px); padding: 12px; margin-bottom: 15px; display: inline-block; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; font-size: 1em; }
    button { background-color: #3498db; color: white; padding: 14px 25px; margin-top: 20px; border: none; border-radius: 5px; cursor: pointer; width: 100%; font-size: 1.1em; transition: background-color 0.3s ease; }
    button:hover { background-color: #2980b9; }
    .footer-note { font-size: 0.9em; color: #7f8c8d; margin-top: 20px; }
  </style>
</head>
<body>
<div class="container">
  <h2>Device Setup Assistant</h2>
  <p><strong>Step 1: Note Your Device Key</strong></p>
  <p class="key-display"><strong>Device API Key:</strong> %DEVICE_API_KEY%</p>
  <p><strong>Step 2: Connect to Your WiFi</strong></p>
  <form action="/save" method="post">
    <label for="ssid">Your Home WiFi SSID:</label>
    <input type="text" id="ssid" name="ssid" placeholder="e.g., MyHomeNetwork" required><br>
    <label for="pass">WiFi Password:</label>
    <input type="password" id="pass" name="password" placeholder="e.g., MyStrongPassword" required><br>
    <button type="submit">Connect to WiFi</button>
  </form>
  <p class="footer-note">After connecting to WiFi, visit our main website to register your device using the API Key above.</p>
</div>
</body>
</html>
)rawliteral";

// --- Sensor & Actuator Pin Definitions ---
#define PZEM_RX_PIN D5 // GPIO14 on NodeMCU (PZEM RX to ESP TX for SoftwareSerial)
#define PZEM_TX_PIN D6 // GPIO12 on NodeMCU (PZEM TX to ESP RX for SoftwareSerial)
#define RELAY_PIN D1   // GPIO5 on NodeMCU (adjust based on your relay module)

// --- Configuration Button Pin ---
// Choose an unused GPIO pin. D3 (GPIO0) is often used for flash, D4 (GPIO2) for LED.
// D8 (GPIO15) is also a good choice, but needs external pull-down.
// D7 (GPIO13) is generally safe.
#define CONFIG_BUTTON_PIN D7 // GPIO13 on NodeMCU. Wire button between D7 and GND.
                             // Uses INPUT_PULLUP, so button press reads LOW.

// --- Global Objects ---
SoftwareSerial pzemSerial(PZEM_RX_PIN, PZEM_TX_PIN);
PZEM004Tv30 pzem(pzemSerial);

// --- Constants ---
// !!! IMPORTANT: CHANGE THIS TO YOUR DJANGO SERVER DOMAIN/IP! !!!
// Example for local development: "192.168.1.105:8000" (replace with your actual PC's IP)
const char* DJANGO_SERVER_DOMAIN = "192.168.0.116:8000";
const char* DEVICE_DATA_ENDPOINT = "/api/v1/device/data/";
const char* DEVICE_COMMAND_ENDPOINT = "/api/v1/device/commands/";

const long SENSOR_SEND_INTERVAL = 10000; // Send data every 10 seconds
const long COMMAND_CHECK_INTERVAL = 5000; // Check commands every 5 seconds
const unsigned long LONG_PRESS_DURATION_MS = 5000; // 5 seconds for a long press to trigger AP mode

// --- Button State Variables ---
int buttonState;             // current reading from the input pin
int lastButtonState = HIGH;  // previous reading from the input pin
unsigned long buttonPressStartTime = 0; // when the button was pressed
bool buttonHandled = false;  // flag to ensure action only on one long press

// --- Function Prototypes ---
void saveConfig();
void loadConfig();
void handleRoot();
void handleSave();
void handleNotFound();
void setupAPMode();
void sendSensorData();
void checkCommands();
void setRelayState(bool state);
void clearEEPROMConfig(); // New function to clear EEPROM
void checkConfigButton(); // New function to check button state

// --- Setup Function ---
void setup() {
  Serial.begin(115200);
  delay(100);

  // Initialize EEPROM with the size of our Config struct
  EEPROM.begin(sizeof(DeviceConfig));
  loadConfig(); // Load existing configuration from EEPROM

  // Initialize CONFIG_BUTTON_PIN
  pinMode(CONFIG_BUTTON_PIN, INPUT_PULLUP); // Use internal pull-up. Button wired to GND.

  // --- Check for button press on boot to force AP mode (Factory Reset) ---
  // If button is held LOW for a short period at boot, force AP mode.
  // This is a "factory reset" trigger.
  Serial.println("Checking for factory reset button press...");
  delay(100); // Give button state time to stabilize
  if (digitalRead(CONFIG_BUTTON_PIN) == LOW) {
    unsigned long bootButtonPressTime = millis();
    while (digitalRead(CONFIG_BUTTON_PIN) == LOW && (millis() - bootButtonPressTime < LONG_PRESS_DURATION_MS)) {
      delay(100);
      Serial.print("#"); // Indicate button being held
    }
    if ((millis() - bootButtonPressTime) >= LONG_PRESS_DURATION_MS) {
      Serial.println("\nLong press detected at boot! Forcing AP mode and clearing config.");
      clearEEPROMConfig(); // Wipe existing WiFi credentials
      setupAPMode(); // Start AP mode
      return; // Exit setup, stay in AP mode loop
    } else {
      Serial.println("\nButton briefly pressed at boot, continuing normal startup.");
    }
  } else {
    Serial.println("No button press detected at boot.");
  }

  // --- Generate / Assign device_api_key if not set (for first production run or testing) ---
  // This block should always execute if the key is "UNSET_KEY" or empty.
  if (strcmp(deviceConfig.device_api_key, "UNSET_KEY") == 0) {
    String macAddr = WiFi.macAddress();
    macAddr.replace(":", "");
    // Ensure the generated key fits within the array size
    String generatedKey = "DEV_" + macAddr.substring(macAddr.length() - 12);
    strncpy(deviceConfig.device_api_key, generatedKey.c_str(), sizeof(deviceConfig.device_api_key) - 1);
    deviceConfig.device_api_key[sizeof(deviceConfig.device_api_key) - 1] = '\0'; // Ensure null termination
    Serial.print("Generated new device_api_key: ");
    Serial.println(deviceConfig.device_api_key);
    saveConfig(); // Save the newly generated key
  }
  Serial.print("Using device_api_key: ");
  Serial.println(deviceConfig.device_api_key);

  // Set device type if not already set (e.g., on first boot)
  if (strcmp(deviceConfig.device_type, "UNSET_TYPE") == 0) {
    strcpy(deviceConfig.device_type, "power_monitor"); // Set the specific type for this device
    saveConfig();
  }
  Serial.print("Device Type: ");
  Serial.println(deviceConfig.device_type);


  // Initialize PZEM serial
  pzemSerial.begin(9600);

  // Initialize relay pin
  pinMode(RELAY_PIN, OUTPUT);
  setRelayState(false); // Ensure relay is off on startup

  // --- Attempt to connect to saved WiFi or start AP mode ---
  if (deviceConfig.configured && strlen(deviceConfig.wifi_ssid) > 0) {
    Serial.print("Attempting to connect to WiFi: ");
    Serial.println(deviceConfig.wifi_ssid);
    WiFi.mode(WIFI_STA); // Explicitly set STA mode
    WiFi.begin(deviceConfig.wifi_ssid, deviceConfig.wifi_password);

    int retries = 0;
    while (WiFi.status() != WL_CONNECTED && retries < 40) { // Max 20 seconds
      delay(500);
      Serial.print(".");
      retries++;
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("\nWiFi connected.");
      Serial.print("IP address: ");
      Serial.println(WiFi.localIP());
    } else {
      Serial.println("\nFailed to connect to WiFi. Starting AP mode for reconfiguration.");
      setupAPMode(); // Fallback to AP if connection fails
    }
  } else {
    Serial.println("Device not configured. Starting AP mode for initial setup.");
    setupAPMode(); // Initial setup mode
  }
}

// --- Loop Function ---
void loop() {
  if (WiFi.getMode() == WIFI_AP) {
    // In AP mode, handle DNS and web server requests for configuration
    dnsServer.processNextRequest();
    webServer.handleClient();
  } else {
    // In STA (client) mode, perform normal operations
    static unsigned long lastSensorSendTime = 0;
    static unsigned long lastCommandCheckTime = 0;

    // Check for long press on config button to re-enter AP mode
    checkConfigButton();

    if (millis() - lastSensorSendTime > SENSOR_SEND_INTERVAL) {
      sendSensorData();
      lastSensorSendTime = millis();
    }

    if (millis() - lastCommandCheckTime > COMMAND_CHECK_INTERVAL) {
      checkCommands();
      lastCommandCheckTime = millis();
    }
  }
  delay(10); // Small delay to yield to other tasks
}

// --- EEPROM Management Functions ---
void saveConfig() {
  EEPROM.put(0, deviceConfig);
  EEPROM.commit(); // Commit changes to flash
  Serial.println("Configuration saved to EEPROM.");
}

void loadConfig() {
  // Read the entire struct from EEPROM
  EEPROM.get(0, deviceConfig);

  // IMPORTANT: Check for a "magic number" or a known good value to validate EEPROM data.
  // For simplicity, we'll check if the device_api_key looks like a valid string.
  // A better approach would be to store a CRC or a specific version byte.

  // Check if the device_api_key is empty or contains non-printable characters (a common sign of corruption)
  // or if it's the "UNSET_KEY" placeholder.
  bool is_key_corrupted = false;
  if (strlen(deviceConfig.device_api_key) == 0 || strcmp(deviceConfig.device_api_key, "UNSET_KEY") == 0) {
      is_key_corrupted = true;
  } else {
      // Check for non-printable characters (simple validation)
      for (int i = 0; i < strlen(deviceConfig.device_api_key); ++i) {
          if (deviceConfig.device_api_key[i] < 32 || deviceConfig.device_api_key[i] > 126) {
              is_key_corrupted = true;
              break;
          }
      }
  }

  if (is_key_corrupted) {
    Serial.println("EEPROM data appears empty or corrupted. Initializing config in RAM.");
    // Clear the entire struct in RAM to ensure no garbage remains
    memset(&deviceConfig, 0, sizeof(DeviceConfig));
    deviceConfig.configured = false;
    strcpy(deviceConfig.device_api_key, "UNSET_KEY"); // Set placeholder
    strcpy(deviceConfig.device_type, "UNSET_TYPE"); // Set placeholder
  } else {
    Serial.println("Configuration loaded from EEPROM.");
  }
}

void clearEEPROMConfig() {
  Serial.println("Clearing EEPROM configuration...");
  // Fill the EEPROM area for DeviceConfig with zeros
  for (int i = 0; i < sizeof(DeviceConfig); ++i) {
    EEPROM.write(i, 0);
  }
  EEPROM.commit();
  // Also clear the in-memory struct to match the cleared EEPROM
  memset(&deviceConfig, 0, sizeof(DeviceConfig));
  deviceConfig.configured = false;
  strcpy(deviceConfig.device_api_key, "UNSET_KEY"); // Reset to trigger re-generation
  strcpy(deviceConfig.device_type, "UNSET_TYPE");
  Serial.println("EEPROM configuration cleared.");
}

// --- SoftAP Web Server Handlers ---
void handleRoot() {
  String html = CONFIG_PORTAL_HTML;
  html.replace("%DEVICE_API_KEY%", deviceConfig.device_api_key);
  webServer.send(200, "text/html", html);
}

void handleSave() {
  String ssid = webServer.arg("ssid");
  String password = webServer.arg("password");

  // Save to EEPROM
  strncpy(deviceConfig.wifi_ssid, ssid.c_str(), sizeof(deviceConfig.wifi_ssid) - 1);
  strncpy(deviceConfig.wifi_password, password.c_str(), sizeof(deviceConfig.wifi_password) - 1);
  deviceConfig.wifi_ssid[sizeof(deviceConfig.wifi_ssid) - 1] = '\0'; // Ensure null termination
  deviceConfig.wifi_password[sizeof(deviceConfig.wifi_password) - 1] = '\0';
  deviceConfig.configured = true;
  saveConfig();

  String message = "Configuration saved! Device will restart and try to connect to: " + ssid;
  webServer.send(200, "text/plain", message);
  Serial.println(message);
  delay(2000);
  ESP.restart(); // Restart the ESP to connect to the new WiFi
}

void handleNotFound() {
  // This is crucial for captive portals: redirect all unknown requests to the root
  webServer.sendHeader("Location", String("http://") + WiFi.softAPIP().toString());
  webServer.send(302, "text/plain", ""); // Send a redirect
}

void setupAPMode() {
  Serial.println("Setting up AP Mode...");
  WiFi.mode(WIFI_AP); // Ensure only AP mode is active
  IPAddress apIP(192, 168, 4, 1);
  IPAddress gateway(192, 168, 4, 1);
  IPAddress subnet(255, 255, 255, 0);
  WiFi.softAPConfig(apIP, gateway, subnet);

  String apSSID = "IoTSetup-" + WiFi.macAddress().substring(9);
  WiFi.softAP(apSSID.c_str());
  Serial.print("Started SoftAP: ");
  Serial.println(apSSID);
  Serial.print("AP IP address: ");
  Serial.println(WiFi.softAPIP());

  // DNS server setup to redirect all requests to our web server
  dnsServer.start(DNS_PORT, "*", apIP); // Use apIP as the DNS server address

  // Web server handlers
  webServer.on("/", handleRoot);
  webServer.on("/save", HTTP_POST, handleSave);
  webServer.onNotFound(handleNotFound); // Catch all other requests and redirect

  webServer.begin();
  Serial.println("Web server started in AP Mode.");
  // Loop indefinitely in AP mode until configuration is saved and device restarts
  while(WiFi.getMode() == WIFI_AP) {
    dnsServer.processNextRequest();
    webServer.handleClient();
    delay(10); // Small delay to yield to other tasks
  }
}

// --- Sensor Reading Function (PZEM-004T Specific) ---
void sendSensorData() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi not connected, skipping sensor data send.");
    return;
  }

  WiFiClient client;
  HTTPClient http;
  String serverPath = "http://" + String(DJANGO_SERVER_DOMAIN) + String(DEVICE_DATA_ENDPOINT);
  http.begin(client, serverPath);
  http.addHeader("Content-Type", "application/json");

  float voltage = pzem.voltage();
  float current = pzem.current();
  float power = pzem.power();
  float energy = pzem.energy(); // kWh
  float frequency = pzem.frequency();
  float pf = pzem.pf();

  if (isnan(voltage) || isnan(current) || isnan(power) || isnan(energy) || isnan(frequency) || isnan(pf)) {
    Serial.println("Error reading PZEM data. Skipping send.");
    return;
  }

  DynamicJsonDocument doc(512);
  doc["device_api_key"] = deviceConfig.device_api_key;
  doc["device_type"] = deviceConfig.device_type;

  JsonObject sensor_data = doc.createNestedObject("sensor_data");
  sensor_data["voltage"] = voltage;
  sensor_data["current"] = current;
  sensor_data["power"] = power;
  sensor_data["energy"] = energy;
  sensor_data["frequency"] = frequency;
  sensor_data["pf"] = pf;
  sensor_data["relay_state"] = digitalRead(RELAY_PIN) == HIGH ? "ON" : "OFF";

  String requestBody;
  serializeJson(doc, requestBody);

  Serial.print("Sending data to: "); Serial.println(serverPath);
  Serial.print("Payload: "); Serial.println(requestBody);

  int httpResponseCode = http.POST(requestBody);

  if (httpResponseCode > 0) {
    Serial.printf("[HTTP] POST... code: %d\n", httpResponseCode);
    String response = http.getString();
    Serial.println(response);
  } else {
    Serial.printf("[HTTP] POST... failed, error: %s\n", http.errorToString(httpResponseCode).c_str());
  }

  http.end();
}

// --- HTTP Communication Functions ---
void checkCommands() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi not connected, skipping command check.");
    return;
  }

  WiFiClient client;
  HTTPClient http;
  String serverPath = "http://" + String(DJANGO_SERVER_DOMAIN) + String(DEVICE_COMMAND_ENDPOINT);
  serverPath += "?device_api_key=" + String(deviceConfig.device_api_key);
  http.begin(client, serverPath);

  Serial.print("Checking for commands from: "); Serial.println(serverPath);

  int httpResponseCode = http.GET();

  if (httpResponseCode > 0) {
    String payload = http.getString();
    Serial.println("Received command payload: " + payload);

    StaticJsonDocument<256> doc;
    DeserializationError error = deserializeJson(doc, payload);

    if (!error && doc.containsKey("command")) {
      String command = doc["command"].as<String>();
      if (command == "set_relay_state") {
        if (doc.containsKey("parameters") && doc["parameters"].containsKey("state")) {
          String state = doc["parameters"]["state"].as<String>();
          if (state == "ON") {
            setRelayState(true);
            Serial.println("Relay turned ON.");
          } else if (state == "OFF") {
            setRelayState(false);
            Serial.println("Relay turned OFF.");
          } else {
            Serial.print("Invalid relay state parameter: "); Serial.println(state);
          }
        } else {
          Serial.println("Missing 'state' parameter for 'set_relay_state' command.");
        }
      } else if (command == "no_command") {
        Serial.println("No pending commands.");
      } else {
        Serial.print("Unknown command: ");
        Serial.println(command);
      }
    } else {
      Serial.println("Invalid JSON or no 'command' key found.");
    }
  } else {
    Serial.printf("[HTTP] GET command failed, error: %s\n", http.errorToString(httpResponseCode).c_str());
  }

  http.end();
}

// --- Actuator Control Functions ---
void setRelayState(bool state) {
  digitalWrite(RELAY_PIN, state ? HIGH : LOW);
}

// --- Button Check Function for Re-configuration ---
void checkConfigButton() {
  int reading = digitalRead(CONFIG_BUTTON_PIN);

  // If the button state has changed
  if (reading != lastButtonState) {
    // Reset the timer if the button is released or just pressed
    if (reading == HIGH) { // Button released
      buttonPressStartTime = 0;
      buttonHandled = false; // Reset flag
    } else { // Button pressed (LOW)
      buttonPressStartTime = millis();
    }
    lastButtonState = reading;
  }

  // If button is currently pressed (LOW) and a long press hasn't been handled yet
  if (reading == LOW && !buttonHandled) {
    if (millis() - buttonPressStartTime >= LONG_PRESS_DURATION_MS) {
      Serial.println("\nLong press detected! Entering AP mode for Wi-Fi reconfiguration.");
      buttonHandled = true; // Mark as handled
      
      // Disconnect from current WiFi
      WiFi.disconnect(true); // Disconnect and turn off WiFi radio
      delay(100); // Give it a moment to disconnect

      clearEEPROMConfig(); // Clear saved Wi-Fi credentials
      setupAPMode(); // Start AP mode for re-configuration
      // Note: setupAPMode() now contains a while loop to keep it in AP mode
      // until a new config is saved and device restarts.
    }
  }
}
