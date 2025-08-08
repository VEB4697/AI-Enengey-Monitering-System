#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <DNSServer.h>
#include <EEPROM.h>
#include <ArduinoJson.h>
#include <ESP8266HTTPClient.h>
#include <PZEM004Tv30.h>
#include <SoftwareSerial.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// This is the modified and expanded code for the ESP8266 device.
// It incorporates an I2C OLED display and a three-button interface
// while retaining all original functionalities.

// --- Configuration Struct (Stored in EEPROM) ---
struct DeviceConfig {
  char wifi_ssid[64];
  char wifi_password[64];
  char device_api_key[37];
  bool configured;
  char device_type[32];
};

DeviceConfig deviceConfig;

// --- OLED Display Configuration ---
#define SCREEN_WIDTH 128    // OLED display width, in pixels
#define SCREEN_HEIGHT 64    // OLED display height, in pixels
#define OLED_RESET -1       // Reset pin # (or -1 if sharing Arduino reset pin)
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// --- Web Server for SoftAP Mode ---
const byte DNS_PORT = 53;
DNSServer dnsServer;
ESP8266WebServer webServer(80);
// This is a placeholder for the HTML content. In a real-world application,
// this would be a more complete HTML page.
const char PROGMEM CONFIG_PORTAL_HTML[] = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <title>IoT Device Setup</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{font-family: Arial, sans-serif;}
    .container { max-width: 400px; margin: 50px auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }
    input[type=text], input[type=password] { width: 100%; padding: 10px; margin: 8px 0; display: inline-block; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
    button { background-color: #4CAF50; color: white; padding: 14px 20px; margin: 8px 0; border: none; cursor: pointer; width: 100%; border-radius: 4px; }
  </style>
</head>
<body>
<div class="container">
  <h2>Wi-Fi Configuration</h2>
  <form action="/save" method="post">
    <label for="ssid">SSID:</label>
    <input type="text" id="ssid" name="ssid" required>
    <label for="password">Password:</label>
    <input type="password" id="password" name="password">
    <button type="submit">Save</button>
  </form>
</div>
</body>
</html>
)rawliteral";

// --- Sensor & Actuator Pin Definitions ---
// Note: We are re-defining the relay pin to avoid conflict with I2C SCL (D1).
// Using D8 (GPIO15) which requires a pull-down resistor.
#define PZEM_RX_PIN D5  // GPIO14
#define PZEM_TX_PIN D6  // GPIO12
#define RELAY_PIN D8    // GPIO15 (Note: D8 is active LOW on boot)

// --- Button Pin Definitions ---
#define WIFI_RESET_BUTTON_PIN D7 // GPIO13
#define READ_SWIPE_BUTTON_PIN D3 // GPIO0
#define RELAY_CONTROL_BUTTON_PIN D4 // GPIO2

// --- Global Objects ---
SoftwareSerial pzemSerial(PZEM_RX_PIN, PZEM_TX_PIN);
PZEM004Tv30 pzem(pzemSerial);

// --- Constants ---
const char* DJANGO_SERVER_DOMAIN = "192.168.0.116:8000";
const char* DEVICE_DATA_ENDPOINT = "/api/v1/device/data/";
const char* DEVICE_COMMAND_ENDPOINT = "/api/v1/device/commands/";
const long SENSOR_SEND_INTERVAL = 10000;
const long COMMAND_CHECK_INTERVAL = 5000;
const unsigned long LONG_PRESS_DURATION_MS = 5000;
const long DISPLAY_UPDATE_INTERVAL = 3000; // 3 seconds to auto-swipe display

// --- Button State Variables ---
unsigned long lastButtonPressTime = 0;
bool wifiResetButtonHandled = false;
unsigned long swipeButtonLastDebounceTime = 0;
unsigned long relayButtonLastDebounceTime = 0;
const unsigned long debounceDelay = 50;
int readSwipeCounter = 0; // To cycle through display values

// --- Display State Variables ---
unsigned long lastDisplayUpdateTime = 0;
int wifiAnimFrame = 0;
bool isDisplayConnected = false;

// --- Function Prototypes ---
void loadConfig();
void saveConfig();
void clearEEPROMConfig();
void sendSensorData();
void checkCommands();
void setRelayState(bool state);
void setupAPMode();
void handleRoot();
void handleSave();
void handleNotFound();
void checkConfigButton();
void setupDisplay();
void displayAPModeInfo();
void displayConnecting(const char* ssid, int frame);
void displayData();
void checkButtons();

// --- Setup Function ---
void setup() {
  Serial.begin(115200);
  delay(100);

  // Initialize and test the OLED display
  setupDisplay();

  // Initialize EEPROM and load saved configuration
  EEPROM.begin(sizeof(DeviceConfig));
  loadConfig();

  // Initialize all button pins with pull-ups
  pinMode(WIFI_RESET_BUTTON_PIN, INPUT_PULLUP);
  pinMode(READ_SWIPE_BUTTON_PIN, INPUT_PULLUP);
  pinMode(RELAY_CONTROL_BUTTON_PIN, INPUT_PULLUP);
  pinMode(RELAY_PIN, OUTPUT); // Configure relay pin as output

  // Check for long press on WiFi Reset button during boot
  if (digitalRead(WIFI_RESET_BUTTON_PIN) == LOW) {
    display.clearDisplay();
    display.setCursor(0, 0);
    display.println("Factory Reset...");
    display.display();
    unsigned long bootButtonPressTime = millis();
    while (digitalRead(WIFI_RESET_BUTTON_PIN) == LOW && (millis() - bootButtonPressTime < LONG_PRESS_DURATION_MS)) {
      delay(100);
    }
    if ((millis() - bootButtonPressTime) >= LONG_PRESS_DURATION_MS) {
      clearEEPROMConfig();
      ESP.restart(); // Restart to enter AP mode
      return;
    }
  }

  // Generate / Assign device_api_key if not set
  if (strlen(deviceConfig.device_api_key) == 0) {
    String mac_address_str = WiFi.macAddress();
    mac_address_str.replace(":", "");
    String uuid_str = mac_address_str; // For this example, use MAC as a simple ID
    uuid_str.toCharArray(deviceConfig.device_api_key, 37);
    saveConfig();
  }

  // Set device type if not already set
  if (strlen(deviceConfig.device_type) == 0) {
    strcpy(deviceConfig.device_type, "power_monitor");
    saveConfig();
  }

  // Initialize PZEM and Relay pin
  pzemSerial.begin(9600);
  setRelayState(false);

  // Attempt to connect to saved WiFi or start AP mode
  if (deviceConfig.configured && strlen(deviceConfig.wifi_ssid) > 0) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(deviceConfig.wifi_ssid, deviceConfig.wifi_password);
    int retries = 0;
    while (WiFi.status() != WL_CONNECTED && retries < 40) {
      displayConnecting(deviceConfig.wifi_ssid, retries);
      delay(500);
      retries++;
    }
    if (WiFi.status() == WL_CONNECTED) {
      display.clearDisplay();
      display.setCursor(0, 0);
      display.println("Connected!");
      display.println(WiFi.localIP());
      display.display();
      delay(2000);
    } else {
      setupAPMode();
    }
  } else {
    setupAPMode();
  }
}

// --- Loop Function ---
void loop() {
  if (WiFi.getMode() == WIFI_AP) {
    dnsServer.processNextRequest();
    webServer.handleClient();
    displayAPModeInfo(); // Update the display in AP mode
  } else {
    // STA (client) mode operations
    static unsigned long lastSensorSendTime = 0;
    static unsigned long lastCommandCheckTime = 0;
    checkButtons(); // Check for button presses

    if (millis() - lastSensorSendTime > SENSOR_SEND_INTERVAL) {
      sendSensorData();
      lastSensorSendTime = millis();
    }

    if (millis() - lastCommandCheckTime > COMMAND_CHECK_INTERVAL) {
      checkCommands();
      lastCommandCheckTime = millis();
    }

    // Auto-swipe the display every 3 seconds
    if (millis() - lastDisplayUpdateTime > DISPLAY_UPDATE_INTERVAL) {
      readSwipeCounter++;
      if (readSwipeCounter > 8) readSwipeCounter = 0;
      lastDisplayUpdateTime = millis();
    }
    displayData(); // Update the display with sensor data
  }
  delay(10);
}

// --- Display-specific Functions ---
void setupDisplay() {
  // Initialize with the I2C address 0x3C for 128x64 display
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println(F("SSD1306 allocation failed"));
    isDisplayConnected = false;
  } else {
    isDisplayConnected = true;
    display.display();
    delay(2000);
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println("ESP8266 Started");
    display.display();
  }
}

void displayAPModeInfo() {
  if (!isDisplayConnected) return;
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("AP Mode Active");
  display.print("SSID: ");
  display.println(String("IoTSetup-") + WiFi.macAddress().substring(9));
  display.print("IP: ");
  display.println(WiFi.softAPIP());
  display.println("----------------");
  display.println("Device Key:");
  display.println(deviceConfig.device_api_key);
  display.display();
}

void displayConnecting(const char* ssid, int frame) {
  if (!isDisplayConnected) return;
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("Connecting to:");
  display.println(ssid);
  // Simple WiFi animation
  display.drawPixel(100 + (frame % 4), 30, SSD1306_WHITE);
  display.display();
}

void displayData() {
  if (!isDisplayConnected) return;
  // Get fresh sensor data
  float voltage = pzem.voltage();
  float current = pzem.current();
  float power = pzem.power();
  float energy = pzem.energy();
  float frequency = pzem.frequency();
  float pf = pzem.pf();
  bool relayState = digitalRead(RELAY_PIN);

  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);

  switch (readSwipeCounter) {
    case 0:
      // Welcome message with a placeholder username.
      display.println("Welcome, User!");
      display.println("Swipe for data.");
      break;
    case 1:
      display.println("Device API Key:");
      display.println(deviceConfig.device_api_key);
      break;
    case 2:
      display.println("Voltage:");
      display.setTextSize(2);
      display.print(voltage);
      display.println(" V");
      break;
    case 3:
      display.println("Current:");
      display.setTextSize(2);
      display.print(current);
      display.println(" A");
      break;
    case 4:
      display.println("Power:");
      display.setTextSize(2);
      display.print(power);
      display.println(" W");
      break;
    case 5:
      display.println("Energy:");
      display.setTextSize(2);
      display.print(energy);
      display.println(" kWh");
      break;
    case 6:
      display.println("Frequency:");
      display.setTextSize(2);
      display.print(frequency);
      display.println(" Hz");
      break;
    case 7:
      display.println("Power Factor:");
      display.setTextSize(2);
      display.println(pf);
      break;
    case 8:
      display.println("Relay State:");
      display.setTextSize(2);
      display.println(relayState ? "ON" : "OFF");
      break;
  }
  display.display();
}

// --- Button Handling Functions ---
void checkButtons() {
  // WiFi Reset Button
  static unsigned long wifiResetPressStartTime = 0;
  static bool wifiResetButtonHeld = false;
  static int lastWifiResetButtonState = HIGH;
  int wifiResetReading = digitalRead(WIFI_RESET_BUTTON_PIN);

  if (wifiResetReading != lastWifiResetButtonState) {
    if (millis() - lastButtonPressTime > debounceDelay) {
      if (wifiResetReading == LOW) {
        wifiResetPressStartTime = millis();
      } else {
        wifiResetPressStartTime = 0;
        wifiResetButtonHeld = false;
      }
    }
    lastWifiResetButtonState = wifiResetReading;
    lastButtonPressTime = millis();
  }

  if (wifiResetReading == LOW && !wifiResetButtonHeld) {
    if (millis() - wifiResetPressStartTime >= LONG_PRESS_DURATION_MS) {
      wifiResetButtonHeld = true;
      display.clearDisplay();
      display.setCursor(0,0);
      display.println("Long press detected!");
      display.println("Resetting...");
      display.display();
      delay(2000);
      clearEEPROMConfig();
      ESP.restart();
    }
  }

  // Relay Control Button
  static int lastRelayButtonState = HIGH;
  int relayReading = digitalRead(RELAY_CONTROL_BUTTON_PIN);
  if (relayReading != lastRelayButtonState) {
    if (millis() - relayButtonLastDebounceTime > debounceDelay) {
      if (relayReading == LOW) {
        bool currentState = digitalRead(RELAY_PIN);
        setRelayState(!currentState);
      }
      relayButtonLastDebounceTime = millis();
    }
    lastRelayButtonState = relayReading;
  }

  // Read Value Swipe Button
  static int lastSwipeButtonState = HIGH;
  int swipeReading = digitalRead(READ_SWIPE_BUTTON_PIN);
  if (swipeReading != lastSwipeButtonState) {
    if (millis() - swipeButtonLastDebounceTime > debounceDelay) {
      if (swipeReading == LOW) {
        readSwipeCounter++;
        if (readSwipeCounter > 8) readSwipeCounter = 0;
        lastDisplayUpdateTime = millis(); // Reset auto-swipe timer
      }
      swipeButtonLastDebounceTime = millis();
    }
    lastSwipeButtonState = swipeReading;
  }
}

// --- Other existing functions (loadConfig, saveConfig, etc.) ---

void loadConfig() {
  EEPROM.get(0, deviceConfig);
}

void saveConfig() {
  EEPROM.put(0, deviceConfig);
  EEPROM.commit();
}

void clearEEPROMConfig() {
  display.clearDisplay();
  display.setCursor(0, 0);
  display.println("Clearing Config...");
  display.display();
  delay(1000);
  EEPROM.begin(sizeof(DeviceConfig));
  for (unsigned int i = 0; i < sizeof(DeviceConfig); i++) {
    EEPROM.write(i, 0);
  }
  EEPROM.commit();
}

void sendSensorData() {
  // This is a placeholder for the actual HTTP request to a Django server.
  // The original functionality is kept.
  HTTPClient http;
  WiFiClient client; // Create a WiFiClient object
  String serverPath = String("http://") + DJANGO_SERVER_DOMAIN + DEVICE_DATA_ENDPOINT;
  http.begin(client, serverPath); // Use the updated begin function
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<200> doc;
  doc["device_api_key"] = deviceConfig.device_api_key;
  doc["voltage"] = pzem.voltage();
  doc["current"] = pzem.current();
  doc["power"] = pzem.power();
  doc["energy"] = pzem.energy();
  doc["frequency"] = pzem.frequency();
  doc["power_factor"] = pzem.pf();

  String httpRequestData;
  serializeJson(doc, httpRequestData);

  int httpResponseCode = http.POST(httpRequestData);

  if (httpResponseCode > 0) {
    Serial.print("HTTP Response code: ");
    Serial.println(httpResponseCode);
  } else {
    Serial.print("Error code: ");
    Serial.println(httpResponseCode);
  }
  http.end();
}

void checkCommands() {
  // This is a placeholder for the actual command check.
  // The original functionality is kept.
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    WiFiClient client; // Create a WiFiClient object
    String serverPath = String("http://") + DJANGO_SERVER_DOMAIN + DEVICE_COMMAND_ENDPOINT + String("?device_api_key=") + deviceConfig.device_api_key;
    http.begin(client, serverPath); // Use the updated begin function
    int httpResponseCode = http.GET();

    if (httpResponseCode > 0) {
      String payload = http.getString();
      StaticJsonDocument<200> doc;
      deserializeJson(doc, payload);

      bool relay_state = doc["relay_state"];
      setRelayState(relay_state);

    } else {
      Serial.print("Error code: ");
      Serial.println(httpResponseCode);
    }
    http.end();
  }
}

void setRelayState(bool state) {
  // Relays are often active LOW, so HIGH means OFF.
  // Adjust this based on your specific relay module.
  digitalWrite(RELAY_PIN, state ? HIGH : LOW);
}

void setupAPMode() {
  Serial.println("Setting up AP Mode...");
  display.clearDisplay();
  display.setCursor(0, 0);
  display.println("AP Mode Setup...");
  display.display();

  String ap_ssid = "IoTSetup-" + WiFi.macAddress().substring(9);
  WiFi.softAP(ap_ssid.c_str());

  dnsServer.start(DNS_PORT, "*", WiFi.softAPIP());
  webServer.on("/", handleRoot);
  webServer.on("/save", handleSave);
  webServer.onNotFound(handleNotFound);
  webServer.begin();

  Serial.println("AP SSID: " + ap_ssid);
  Serial.println("AP IP: " + WiFi.softAPIP().toString());
}

void handleRoot() {
  webServer.send(200, "text/html", CONFIG_PORTAL_HTML);
}

void handleSave() {
  if (webServer.hasArg("ssid") && webServer.hasArg("password")) {
    String ssid = webServer.arg("ssid");
    String password = webServer.arg("password");
    ssid.toCharArray(deviceConfig.wifi_ssid, 64);
    password.toCharArray(deviceConfig.wifi_password, 64);
    deviceConfig.configured = true;
    saveConfig();
    webServer.send(200, "text/plain", "Configuration saved! Restarting...");
    delay(3000);
    ESP.restart();
  } else {
    webServer.send(400, "text/plain", "Invalid request");
  }
}

void handleNotFound() {
  webServer.send(404, "text/plain", "File Not Found");
}

