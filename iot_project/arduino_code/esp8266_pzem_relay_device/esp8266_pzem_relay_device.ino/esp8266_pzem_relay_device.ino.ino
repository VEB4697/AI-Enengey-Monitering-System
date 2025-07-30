// --- Libraries ---
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <DNSServer.h>
#include <EEPROM.h>
#include <ArduinoJson.h>    // For JSON parsing/serialization
#include <ESP8266HTTPClient.h>     // For making HTTP requests
#include <PZEM004Tv30.h>    // Library for PZEM-004T v30
#include <SoftwareSerial.h> // For connecting PZEM to ESP8266 using SoftwareSerial

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
// For loading from data/index.html, you'd use SPIFFS or LittleFS:
// #include <FS.h>
// File file = SPIFFS.open("/index.html", "r");
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

// --- Sensor Pin Definitions ---
#define PZEM_RX_PIN D5 // GPIO14 on NodeMCU
#define PZEM_TX_PIN D6 // GPIO12 on NodeMCU
#define RELAY_PIN D1 // GPIO5 on NodeMCU

// --- Global Objects ---
SoftwareSerial pzemSerial(PZEM_RX_PIN, PZEM_TX_PIN);
PZEM004Tv30 pzem(pzemSerial);

// --- Constants ---
const char* DJANGO_SERVER_DOMAIN = "your_django_server_domain.com"; // CHANGE THIS TO YOUR DJANGO SERVER DOMAIN/IP!
const char* DEVICE_DATA_ENDPOINT = "/api/v1/device/data/";
const char* DEVICE_COMMAND_ENDPOINT = "/api/v1/device/commands/";

// --- Function Prototypes ---
void saveConfig();
void loadConfig();
void handleRoot();
void handleSave();
void handleNotFound(); // New: for handling non-existent paths
void setupAPMode();
void sendSensorData();
void checkCommands();
void setRelayState(bool state);

// --- Setup Function ---
void setup() {
  Serial.begin(115200);
  delay(100);

  EEPROM.begin(sizeof(DeviceConfig)); // Corrected struct name
  loadConfig();

  if (strlen(deviceConfig.device_type) == 0 || strcmp(deviceConfig.device_type, "UNSET_TYPE") == 0) {
    strcpy(deviceConfig.device_type, "power_monitor");
    saveConfig();
  }
  Serial.print("Device Type: ");
  Serial.println(deviceConfig.device_type);

  if (strlen(deviceConfig.device_api_key) == 0 || strcmp(deviceConfig.device_api_key, "UNSET_KEY") == 0) {
    String macAddr = WiFi.macAddress();
    macAddr.replace(":", "");
    String generatedKey = "DEV_" + macAddr.substring(macAddr.length() - 12);
    strcpy(deviceConfig.device_api_key, generatedKey.c_str());
    Serial.print("Generated new device_api_key: ");
    Serial.println(deviceConfig.device_api_key);
    saveConfig();
  }
  Serial.print("Using device_api_key: ");
  Serial.println(deviceConfig.device_api_key);

  pzemSerial.begin(9600);

  pinMode(RELAY_PIN, OUTPUT);
  setRelayState(false);

  if (deviceConfig.configured && strlen(deviceConfig.wifi_ssid) > 0) {
    Serial.print("Attempting to connect to WiFi: ");
    Serial.println(deviceConfig.wifi_ssid);
    WiFi.begin(deviceConfig.wifi_ssid, deviceConfig.wifi_password);

    int retries = 0;
    while (WiFi.status() != WL_CONNECTED && retries < 40) {
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
      setupAPMode();
    }
  } else {
    Serial.println("Device not configured. Starting AP mode for initial setup.");
    setupAPMode();
  }
}

// --- Loop Function ---
void loop() {
  if (WiFi.getMode() == WIFI_AP) {
    dnsServer.processNextRequest();
    webServer.handleClient();
  } else {
    static unsigned long lastSensorSendTime = 0;
    static unsigned long lastCommandCheckTime = 0;
    const long SENSOR_SEND_INTERVAL = 10000;
    const long COMMAND_CHECK_INTERVAL = 5000;

    if (millis() - lastSensorSendTime > SENSOR_SEND_INTERVAL) {
      sendSensorData();
      lastSensorSendTime = millis();
    }

    if (millis() - lastCommandCheckTime > COMMAND_CHECK_INTERVAL) {
      checkCommands();
      lastCommandCheckTime = millis();
    }
  }
  delay(10);
}

// --- EEPROM Management Functions ---
void saveConfig() {
  EEPROM.put(0, deviceConfig);
  EEPROM.commit();
  Serial.println("Configuration saved to EEPROM.");
}

void loadConfig() {
  EEPROM.get(0, deviceConfig);
  if (strlen(deviceConfig.device_api_key) == 0 || strcmp(deviceConfig.device_api_key, "UNSET_KEY") == 0) {
    Serial.println("EEPROM is empty or invalid. Initializing config.");
    deviceConfig.configured = false;
    strcpy(deviceConfig.device_api_key, "UNSET_KEY");
    strcpy(deviceConfig.device_type, "UNSET_TYPE");
  } else {
    Serial.println("Configuration loaded from EEPROM.");
  }
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

  strncpy(deviceConfig.wifi_ssid, ssid.c_str(), sizeof(deviceConfig.wifi_ssid) - 1);
  strncpy(deviceConfig.wifi_password, password.c_str(), sizeof(deviceConfig.wifi_password) - 1);
  deviceConfig.wifi_ssid[sizeof(deviceConfig.wifi_ssid) - 1] = '\0';
  deviceConfig.wifi_password[sizeof(deviceConfig.wifi_password) - 1] = '\0';
  deviceConfig.configured = true;
  saveConfig();

  String message = "Configuration saved! Device will restart and try to connect to: " + ssid;
  webServer.send(200, "text/plain", message);
  Serial.println(message);
  delay(2000);
  ESP.restart();
}

void handleNotFound() {
  // This is crucial for captive portals: redirect all unknown requests to the root
  webServer.sendHeader("Location", String("http://") + WiFi.softAPIP().toString()); // FIX: Use .toString()
  webServer.send(302, "text/plain", ""); // Send a redirect
}


void setupAPMode() {
  Serial.println("Setting up AP Mode...");
  WiFi.mode(WIFI_AP);
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
            setRelayState(true); // Corrected typo here
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
