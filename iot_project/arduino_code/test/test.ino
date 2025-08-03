// --- Libraries ---
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <DNSServer.h>
#include <EEPROM.h>
#include <ArduinoJson.h>     // For JSON parsing/serialization
#include <ESP8266HTTPClient.h> // For making HTTP requests
// The PZEM library is not needed for this simulation
// #include <PZEM004Tv30.h> 
// #include <SoftwareSerial.h>

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
WiFiClient client;

// HTML for the config portal (simplified, for actual use, load from data/index.html)
const char PROGMEM CONFIG_PORTAL_HTML[] = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <title>IoT Device Setup</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; text-align: center; margin: 50px; background-color: #2c3e50; color: #ecf0f1; }
    input, button, select { border: 1px solid #3498db; border-radius: 5px; padding: 10px; margin: 5px; width: 80%; max-width: 300px; box-sizing: border-box; }
    button { background-color: #3498db; color: white; cursor: pointer; }
    h2 { color: #3498db; }
  </style>
</head>
<body>
  <h2>IoT Device Setup</h2>
  <form action="/save" method="post">
    <input type="text" name="ssid" placeholder="WiFi SSID"><br>
    <input type="password" name="password" placeholder="WiFi Password"><br>
    <input type="text" name="device_api_key" placeholder="Device API Key"><br>
    <button type="submit">Save & Connect</button>
  </form>
</body>
</html>
)rawliteral";

// --- Simulate Sensor Data Variables ---
float simulated_voltage = 230.0;
float simulated_current = 0.5;
float simulated_power = 0.0;
float simulated_energy = 0.0;
unsigned long last_data_update = 0;
const unsigned long DATA_UPDATE_INTERVAL = 5000; // Update every 5 seconds

// --- Pins ---
const int RELAY_PIN = D5;
const int CONFIG_BUTTON_PIN = D3;
const unsigned long LONG_PRESS_DURATION_MS = 5000; // 5 seconds
int lastButtonState = HIGH;
unsigned long buttonPressStartTime = 0;
bool buttonHandled = false;

// --- Function Prototypes ---
void clearEEPROMConfig();
void setupAPMode();
void handleSaveConfig();
void handleRoot();
void sendDataToServer();
void setRelayState(bool state);
void checkConfigButton();

// --- Setup ---
void setup() {
  Serial.begin(115200);
  delay(10);

  pinMode(RELAY_PIN, OUTPUT);
  pinMode(CONFIG_BUTTON_PIN, INPUT_PULLUP);
  setRelayState(false); // Start with the relay off

  EEPROM.begin(sizeof(DeviceConfig));
  EEPROM.get(0, deviceConfig);

  // If the device is configured, connect to WiFi
  if (deviceConfig.configured) {
    Serial.println("Device is already configured. Connecting to WiFi...");
    WiFi.begin(deviceConfig.wifi_ssid, deviceConfig.wifi_password);

    int max_attempts = 30; // 30*500ms = 15 seconds timeout
    while (WiFi.status() != WL_CONNECTED && max_attempts > 0) {
      delay(500);
      Serial.print(".");
      max_attempts--;
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("\nWiFi connected.");
      Serial.print("IP Address: ");
      Serial.println(WiFi.localIP());
      Serial.print("Device API Key: ");
      Serial.println(deviceConfig.device_api_key);
    } else {
      Serial.println("\nFailed to connect to WiFi. Entering AP mode for reconfiguration.");
      setupAPMode();
    }
  } else {
    Serial.println("Device not configured. Starting in AP mode.");
    setupAPMode();
  }
}

// --- Main Loop ---
void loop() {
  // If in AP mode, handle web server requests
  if (WiFi.getMode() == WIFI_AP) {
    dnsServer.processNextRequest();
    webServer.handleClient();
  } else {
    // We are in normal station mode, so send data
    if (millis() - last_data_update > DATA_UPDATE_INTERVAL) {
        // We will simulate the sensor data here
        simulated_voltage = 220.0 + (random(0, 100) / 10.0) - 5; // e.g., 215-225V
        simulated_current = (random(0, 500) / 100.0) + 0.1; // e.g., 0.1-5.1A
        simulated_power = simulated_voltage * simulated_current;
        simulated_energy += simulated_power * (DATA_UPDATE_INTERVAL / 3600000.0); // KWH calculation
        
        Serial.print("Simulated Data -> ");
        Serial.print("V: "); Serial.print(simulated_voltage);
        Serial.print(", A: "); Serial.print(simulated_current);
        Serial.print(", W: "); Serial.print(simulated_power);
        Serial.print(", KWH: "); Serial.println(simulated_energy);

        sendDataToServer();
        last_data_update = millis();
    }
  }

  // Check the config button regardless of mode
  checkConfigButton();
}

// --- Device Configuration Functions ---
void clearEEPROMConfig() {
  DeviceConfig defaultConfig = { "", "", "", false, "" };
  EEPROM.put(0, defaultConfig);
  EEPROM.commit();
}

void setupAPMode() {
  Serial.println("Starting SoftAP for configuration...");
  WiFi.mode(WIFI_AP);
  WiFi.softAP("Smart-IoT-Device", "12345678");

  IPAddress apIP(192, 168, 4, 1);
  IPAddress subnet(255, 255, 255, 0);
  WiFi.softAPConfig(apIP, apIP, subnet);

  dnsServer.start(DNS_PORT, "*", apIP);
  webServer.on("/", handleRoot);
  webServer.on("/save", handleSaveConfig);
  webServer.begin();
}

void handleSaveConfig() {
  if (webServer.hasArg("ssid") && webServer.hasArg("password") && webServer.hasArg("device_api_key")) {
    String ssid = webServer.arg("ssid");
    String password = webServer.arg("password");
    String apiKey = webServer.arg("device_api_key");

    // Copy to config struct
    ssid.toCharArray(deviceConfig.wifi_ssid, sizeof(deviceConfig.wifi_ssid));
    password.toCharArray(deviceConfig.wifi_password, sizeof(deviceConfig.wifi_password));
    apiKey.toCharArray(deviceConfig.device_api_key, sizeof(deviceConfig.device_api_key));
    deviceConfig.configured = true;
    strcpy(deviceConfig.device_type, "power_monitor");

    EEPROM.put(0, deviceConfig);
    EEPROM.commit();

    webServer.send(200, "text/plain", "Configuration saved. Device will restart and connect to WiFi.");
    delay(1000);
    ESP.restart();
  }
}

void handleRoot() {
  webServer.send(200, "text/html", CONFIG_PORTAL_HTML);
}

// --- Data Sending Function ---
void sendDataToServer() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi not connected. Skipping data send.");
    return;
  }

  HTTPClient http;
  
  // This URL must match your Django API endpoint for receiving data
  String serverPath = "http://192.168.0.116:8000/api/v1/device/data/";
  
  // The device API key is used for authentication
  String deviceApiKey = deviceConfig.device_api_key;
  
    // Create JSON payload in correct nested format
  StaticJsonDocument<512> doc;
  doc["device_api_key"] = deviceApiKey;
  doc["device_type"] = "power_monitor";

  JsonObject sensorData = doc.createNestedObject("sensor_data");
  sensorData["voltage"] = simulated_voltage;
  sensorData["current"] = simulated_current;
  sensorData["power"] = simulated_power;
  sensorData["energy"] = simulated_energy;

  
  String jsonPayload;
  serializeJson(doc, jsonPayload);

  Serial.println("Sending data to server...");
  Serial.println(jsonPayload);

  http.begin(client, serverPath);
  http.addHeader("Content-Type", "application/json");

  int httpResponseCode = http.POST(jsonPayload);
  
  if (httpResponseCode > 0) {
    Serial.print("HTTP Response code: ");
    Serial.println(httpResponseCode);
    String response = http.getString();
    Serial.println(response);

    // Check for success or specific error messages from the server
    StaticJsonDocument<256> responseDoc;
    DeserializationError error = deserializeJson(responseDoc, response);
    if (!error && responseDoc["relay_state"]) {
        bool relayState = responseDoc["relay_state"];
        setRelayState(relayState);
        Serial.print("Relay state received from server: ");
        Serial.println(relayState ? "ON" : "OFF");
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
    }
  }
}