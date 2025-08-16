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
// The HTML content is now dynamically generated in handleRoot()
// and not a static PROGMEM string anymore.

// --- Sensor & Actuator Pin Definitions ---
#define PZEM_RX_PIN D5  // GPIO14
#define PZEM_TX_PIN D6  // GPIO12
#define RELAY_PIN D0    // GPIO16 (Note: D0 is active HIGH on boot, so it's a good choice for active-low relay)

// --- Button Pin Definitions ---
#define WIFI_RESET_BUTTON_PIN D7 // GPIO13
#define READ_SWIPE_BUTTON_PIN D3 // GPIO0
#define RELAY_CONTROL_BUTTON_PIN D4 // GPIO2

// --- Global Objects ---
SoftwareSerial pzemSerial(PZEM_RX_PIN, PZEM_TX_PIN);
PZEM004Tv30 pzem(pzemSerial);
const char* DJANGO_SERVER_DOMAIN = "192.168.0.116:8000";

// --- Constants ---
const char* DEVICE_DATA_ENDPOINT = "/api/v1/device/data/";
const char* DEVICE_COMMAND_ENDPOINT = "/api/v1/device/commands/";
const long SENSOR_SEND_INTERVAL = 4000; // Increased interval for stable comms
const long COMMAND_CHECK_INTERVAL = 5000;
const unsigned long LONG_PRESS_DURATION_MS = 5000;
const long DISPLAY_UPDATE_INTERVAL = 3000; // 3 seconds to auto-swipe display

// --- Button State Variables ---
// Note: Each button now has its own debounce timer for robust handling
unsigned long wifiResetButtonLastDebounceTime = 0;
unsigned long swipeButtonLastDebounceTime = 0;
unsigned long relayButtonLastDebounceTime = 0;
const unsigned long debounceDelay = 50; // Milliseconds for debounce

// State tracking for long press of WiFi Reset button
bool wifiResetButtonHeld = false;
unsigned long wifiResetPressStartTime = 0;

// Counter for display swipe
int readSwipeCounter = 0; 

// --- Display State Variables ---
unsigned long lastDisplayUpdateTime = 0;
int wifiAnimFrame = 0;
bool isDisplayConnected = false;

// --- Global state flag for WiFi connection attempt
volatile bool shouldConnectToNewWifi = false;

// --- Function Prototypes ---
void loadConfig();
void saveConfig();
void clearEEPROMConfig();
void sendSensorData();
void checkCommands();
void setRelayState(bool state); // Keep the prototype here.
void setupAPMode();
void handleRoot();
void handleSave();
void handleNotFound();
void setupDisplay();
void displayAPModeInfo();
void displayConnecting(const char* ssid, int frame);
void displayData();
void checkButtons();
void attemptConnect(); // New function prototype

// --- setRelayState Function Definition (MOVED HERE to resolve 'undefined reference' errors) ---
void setRelayState(bool state) {
  // Relay is active LOW, so 'true' (ON) means digitalWrite(LOW), 'false' (OFF) means digitalWrite(HIGH).
  digitalWrite(RELAY_PIN, state ? LOW : HIGH); 
  Serial.print("Setting relay state to: ");
  Serial.println(state ? "ON (LOW)" : "OFF (HIGH)");
}

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
  // INPUT_PULLUP means the pin will be HIGH when button is NOT pressed, LOW when pressed
  pinMode(WIFI_RESET_BUTTON_PIN, INPUT);
  pinMode(READ_SWIPE_BUTTON_PIN, INPUT);
  pinMode(RELAY_CONTROL_BUTTON_PIN, INPUT);
  pinMode(RELAY_PIN, OUTPUT); // Configure relay pin as output

  // Debugging: Print initial button pin states
  Serial.print("Initial WIFI_RESET_BUTTON_PIN (D7) state: ");
  Serial.println(digitalRead(WIFI_RESET_BUTTON_PIN));
  Serial.print("Initial READ_SWIPE_BUTTON_PIN (D3) state: "); 
  Serial.println(digitalRead(READ_SWIPE_BUTTON_PIN));
  Serial.print("Initial RELAY_CONTROL_BUTTON_PIN (D4) state: "); 
  Serial.println(digitalRead(RELAY_CONTROL_BUTTON_PIN));


  // Initial state for relay: OFF (HIGH for active-low relay)
  setRelayState(false); // This call is now after the function definition.

  // Check for long press on WiFi Reset button during boot
  // This allows factory reset by holding the button during power-on
  delay(100); 
  if (digitalRead(WIFI_RESET_BUTTON_PIN) == LOW) {
    unsigned long bootButtonPressTime = millis();
    while (digitalRead(WIFI_RESET_BUTTON_PIN) == LOW && (millis() - bootButtonPressTime < LONG_PRESS_DURATION_MS)) {
      display.clearDisplay();
      display.setCursor(0, 0);
      display.println("Holding for Factory Reset...");
      display.display();
      delay(100);
    }
    if ((millis() - bootButtonPressTime) >= LONG_PRESS_DURATION_MS) {
      display.clearDisplay();
      display.setCursor(0, 0);
      display.println("Factory Resetting...");
      display.display();
      delay(2000);
      clearEEPROMConfig();
      setupAPMode();
      return; 
    }
  }

  // Generate / Assign device_api_key if not set
  if (strlen(deviceConfig.device_api_key) == 0) {
    String mac_address_str = WiFi.macAddress();
    mac_address_str.replace(":", "");
    String uuid_str = mac_address_str;
    uuid_str.toCharArray(deviceConfig.device_api_key, 37);
    saveConfig();
  }

  // Set device type if not already set
  if (strlen(deviceConfig.device_type) == 0) {
    strcpy(deviceConfig.device_type, "power_monitor");
    saveConfig();
  }

  // Initialize PZEM
  pzemSerial.begin(9600);

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
      Serial.println("Failed to connect with saved credentials. Entering AP mode.");
      setupAPMode();
    }
  } else {
    Serial.println("No saved WiFi config. Entering AP mode.");
    setupAPMode();
  }
}

// --- Loop Function ---
void loop() {
  // If a new WiFi connection attempt is pending from handleSave(), execute it
  if (shouldConnectToNewWifi) {
    attemptConnect();
  }
  
  if (WiFi.getMode() == WIFI_AP) {
    // If in Access Point mode, handle web server and DNS
    dnsServer.processNextRequest();
    webServer.handleClient();
    displayAPModeInfo(); // Update the display in AP mode
  } else {
    // If in STA (client) mode, perform sensor readings and communication with backend
    static unsigned long lastSensorSendTime = 0;
    static unsigned long lastCommandCheckTime = 0;
    
    // Always check buttons in STA mode
    checkButtons(); 

    // Send sensor data periodically
    if (millis() - lastSensorSendTime > SENSOR_SEND_INTERVAL) {
      sendSensorData();
      lastSensorSendTime = millis();
    }

    // Check for pending commands periodically
    if (millis() - lastCommandCheckTime > COMMAND_CHECK_INTERVAL) {
      checkCommands();
      lastCommandCheckTime = millis();
    }

    // Auto-swipe the display every 3 seconds
    if (millis() - lastDisplayUpdateTime > DISPLAY_UPDATE_INTERVAL) {
      readSwipeCounter++;
      if (readSwipeCounter > 8) readSwipeCounter = 0; // Cycle through 0-8
      lastDisplayUpdateTime = millis();
    }
    displayData(); // Update the OLED display with sensor data
  }
  delay(10); // Small delay to prevent watchdog timer resets
}

// --- Display-specific Functions ---
void setupDisplay() {
  // Initialize with the I2C address 0x3C for 128x64 display
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println(F("SSD1306 allocation failed"));
    isDisplayConnected = false;
  } else {
    isDisplayConnected = true;
    display.display(); // Clear display buffer
    delay(2000); // Pause for 2 seconds
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println("ESP8266 Started");
    display.display();
  }
}

void displayAPModeInfo() {
  if (!isDisplayConnected) return; // Don't try to draw if display isn't connected
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
  // Simple WiFi animation (frame varies from 0 to 3)
  wifiAnimFrame = (wifiAnimFrame + 1) % 4; // Advance frame
  for(int i = 0; i < wifiAnimFrame + 1; ++i) {
      display.drawPixel(100 + (i * 5), 30, SSD1306_WHITE);
  }
  display.display();
}

void displayData() {
  if (!isDisplayConnected) return;
  // Get fresh sensor data readings from PZEM
  float voltage = pzem.voltage();
  float current = pzem.current();
  float power = pzem.power();
  float energy = pzem.energy();
  float frequency = pzem.frequency();
  float pf = pzem.pf();
  // Read the actual relay pin state. For active-low relay, LOW means ON and HIGH means OFF
  bool relayState = (digitalRead(RELAY_PIN) == LOW); 

  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);

  // Cycle through different data displays based on readSwipeCounter
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
  unsigned long currentMillis = millis(); // Get current time once for all buttons

  // --- WiFi Reset Button (Long Press for Factory Reset) ---
  static int lastWifiResetButtonState = HIGH; 
  int wifiResetReading = digitalRead(WIFI_RESET_BUTTON_PIN);

  // Check if button state has changed for debouncing
  if (wifiResetReading != lastWifiResetButtonState) {
    wifiResetButtonLastDebounceTime = currentMillis; 
  }

  // Check if debounce time has passed and update last state if stable
  if ((currentMillis - wifiResetButtonLastDebounceTime) > debounceDelay) {
    if (wifiResetReading != lastWifiResetButtonState) { // Only update if actual state differs after debounce
      lastWifiResetButtonState = wifiResetReading;

      if (lastWifiResetButtonState == LOW) { // Button just pressed (stable LOW)
        wifiResetPressStartTime = currentMillis;
        wifiResetButtonHeld = false;
      } else { // Button just released (stable HIGH)
        wifiResetPressStartTime = 0;
        wifiResetButtonHeld = false;
      }
    }
  }

  // Check for long press ONLY if button is currently LOW and hasn't been handled yet
  // Using digitalRead directly here to check current physical state, not debounced state.
  if (digitalRead(WIFI_RESET_BUTTON_PIN) == LOW && !wifiResetButtonHeld) { 
    if ((currentMillis - wifiResetPressStartTime) >= LONG_PRESS_DURATION_MS && wifiResetPressStartTime != 0) {
      wifiResetButtonHeld = true;
      Serial.println("\nLong press detected! Entering AP mode for Wi-Fi reconfiguration.");
      display.clearDisplay();
      display.setCursor(0,0);
      display.println("Long press detected!");
      display.println("Factory Resetting...");
      display.display();
      delay(2000); 
      clearEEPROMConfig();
      WiFi.disconnect(true);
      delay(100); 
      setupAPMode();
    }
  }

  // --- Relay Control Button ---
  static int lastRelayButtonState = HIGH; 
  int relayReading = digitalRead(RELAY_CONTROL_BUTTON_PIN);

  // Check if button state has changed for debouncing
  if (relayReading != lastRelayButtonState) {
    relayButtonLastDebounceTime = currentMillis; 
  }

  // Check if debounce time has passed and update last state if stable
  if ((currentMillis - relayButtonLastDebounceTime) > debounceDelay) {
    if (relayReading != lastRelayButtonState) { // Only update if actual state differs after debounce
      lastRelayButtonState = relayReading;
      if (lastRelayButtonState == LOW) { // Button just pressed (stable LOW)
        bool currentState = (digitalRead(RELAY_PIN) == LOW); 
        setRelayState(!currentState);
        Serial.print("Relay Toggled: ");
        Serial.println(digitalRead(RELAY_PIN) == LOW ? "ON" : "OFF");
      }
    }
  }
  
  // --- Read Value Swipe Button ---
  static int lastSwipeButtonState = HIGH; 
  int swipeReading = digitalRead(READ_SWIPE_BUTTON_PIN);


  // Check if button state has changed for debouncing
  if (swipeReading != lastSwipeButtonState) {
    swipeButtonLastDebounceTime = currentMillis;
    Serial.println("SWIPE State Change Detected (Raw)");
  }

  // Check if debounce time has passed and update last state if stable
  if ((currentMillis - swipeButtonLastDebounceTime) > debounceDelay) {
    if (swipeReading != lastSwipeButtonState) { // Only update if actual state differs after debounce
      lastSwipeButtonState = swipeReading; // Update last state ONLY when stable
      if (lastSwipeButtonState == LOW) { // Stable button press (LOW)
        readSwipeCounter++;
        if (readSwipeCounter > 8) readSwipeCounter = 0; // Cycle counter
        lastDisplayUpdateTime = currentMillis;
        Serial.print("SWIPE Action Triggered! Counter: ");
        Serial.println(readSwipeCounter);
      }
    }
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
  HTTPClient http;
  WiFiClient client;
  String serverPath = String("http://") + DJANGO_SERVER_DOMAIN + DEVICE_DATA_ENDPOINT;
  http.begin(client, serverPath);
  http.addHeader("Content-Type", "application/json");

  // Create the main JSON document
  StaticJsonDocument<500> doc; // Increased size to accommodate nested structure

  // Add top-level fields
  doc["device_api_key"] = deviceConfig.device_api_key;
  doc["device_type"] = deviceConfig.device_type; // Include device_type

  // Create a nested JSON object for sensor_data
  JsonObject sensor_data_obj = doc.createNestedObject("sensor_data");

  // Populate the nested sensor_data object with readings
  sensor_data_obj["voltage"] = pzem.voltage();
  sensor_data_obj["current"] = pzem.current();
  sensor_data_obj["power"] = pzem.power();
  sensor_data_obj["energy"] = pzem.energy();
  sensor_data_obj["frequency"] = pzem.frequency();
  sensor_data_obj["power_factor"] = pzem.pf();
  // Include relay state in sensor data
  sensor_data_obj["relay_state"] = (digitalRead(RELAY_PIN) == LOW); // true if ON, false if OFF

  String httpRequestData;
  serializeJson(doc, httpRequestData);

  Serial.print("Sending data: ");
  Serial.println(httpRequestData); // Print the full JSON payload for debugging

  int httpResponseCode = http.POST(httpRequestData);

  if (httpResponseCode > 0) {
    Serial.print("HTTP Response code: ");
    Serial.println(httpResponseCode);
    String responsePayload = http.getString(); // Read server response
    Serial.print("Server Response: ");
    Serial.println(responsePayload); // Print server response for debugging
  } else {
    Serial.print("Error code: ");
    Serial.println(httpResponseCode);
    Serial.print("HTTP Error: ");
    Serial.println(http.errorToString(httpResponseCode)); // More detailed error
  }
  http.end();
}

void checkCommands() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    WiFiClient client;
    String serverPath = String("http://") + DJANGO_SERVER_DOMAIN + DEVICE_COMMAND_ENDPOINT + String("?device_api_key=") + deviceConfig.device_api_key;
    http.begin(client, serverPath);
    int httpResponseCode = http.GET();

    if (httpResponseCode > 0) {
      String payload = http.getString();
      Serial.print("Received command payload: "); 
      Serial.println(payload); 

      StaticJsonDocument<200> doc;
      DeserializationError error = deserializeJson(doc, payload);

      if (error) {
        Serial.print(F("deserializeJson() failed for commands: "));
        Serial.println(error.f_str());
        return; 
      }

      if (doc.containsKey("command") && doc["command"].as<String>() == "no_command") {
        Serial.println("No pending command.");
      } else if (doc.containsKey("command")) {
        String command_type = doc["command"].as<String>();
        Serial.print("Received command: ");
        Serial.println(command_type);

        if (command_type == "set_relay_state" && doc.containsKey("parameters")) {
          JsonObject params = doc["parameters"].as<JsonObject>();
          if (params.containsKey("relay_state")) {
            // Read as boolean. Ensure backend sends true/false.
            bool relay_state = params["relay_state"].as<bool>();
            Serial.println(relay_state);
            setRelayState(relay_state);
          } else {
            Serial.println("Missing 'relay_state' parameter for 'set_relay_state' command.");
          }
        } else {
          Serial.print("Unhandled command type or missing parameters: ");
          Serial.println(command_type);
        }
      } else {
         Serial.println("Unknown response format from commands endpoint. (Missing 'command' key)");
      }

    } else {
      Serial.print("Error code: ");
      Serial.println(httpResponseCode);
      Serial.print("HTTP Error: ");
      Serial.println(http.errorToString(httpResponseCode));
    }
    http.end();
  }
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

// Modified handleRoot to scan for networks and generate HTML
void handleRoot() {
  String html = R"rawliteral(
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>IoT Device Setup</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Orbitron:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        /* General Body and Theme Setup */
        :root {
            --background-start: hsl(210, 50%, 5%);
            --background-end: hsl(240, 50%, 5%);
            --primary: hsl(195, 100%, 50%); /* Bright Cyan */
            --secondary: hsl(240, 100%, 70%); /* Bright Blue */
            --accent: hsl(180, 100%, 50%); /* Aqua */
            --opposite-glow: hsl(85, 100%, 50%); /* Vibrant neon yellow/green */
            --text-light: hsl(210, 40%, 98%);
            --text-muted: hsl(215, 20%, 65%);
            --card-bg: hsla(220, 30%, 10%, 0.8);
            --input-bg: hsla(220, 30%, 15%, 0.6);
            --border-color: hsla(240, 100%, 70%, 0.3);

            --gradient-animated: linear-gradient(135deg, var(--secondary), var(--primary), var(--accent));
        }
        
        body {
            font-family: 'Inter', sans-serif;
            color: var(--text-light);
            background: var(--background-start);
            min-height: 100vh;
            overflow: hidden; /* Prevent scroll bars from sparkle animation */
            display: flex;
            justify-content: center;
            align-items: center;
            position: relative;
            animation: background-gradient-anim 10s ease-in-out infinite alternate;
        }
        
        /* Background Animations from profile.html */
        @keyframes background-gradient-anim {
            0% {
                background-color: var(--background-start);
                background-image: radial-gradient(circle at 10% 90%, var(--primary) 0%, transparent 50%),
                                  radial-gradient(circle at 90% 10%, var(--secondary) 0%, transparent 50%);
            }
            100% {
                background-color: var(--background-end);
                background-image: radial-gradient(circle at 90% 10%, var(--primary) 0%, transparent 50%),
                                  radial-gradient(circle at 10% 90%, var(--secondary) 0%, transparent 50%);
            }
        }
        
        .sparkles {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            overflow: hidden;
            z-index: 1;
        }

        .sparkle {
            position: absolute;
            background: rgba(255, 255, 255, 0.8);
            border-radius: 50%;
            animation: sparkle-anim 5s linear infinite;
        }

        @keyframes sparkle-anim {
            0% { transform: scale(0); opacity: 0; }
            50% { transform: scale(1); opacity: 1; }
            100% { transform: scale(0); opacity: 0; }
        }

        /* Container and Card Styling */
        .container {
            position: relative;
            z-index: 10;
            max-width: 450px;
            margin: 50px auto;
            padding: 30px;
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            backdrop-filter: blur(10px);
            box-shadow: 0 0 20px rgba(0, 0, 0, 0.5), 0 0 15px var(--primary);
            animation: fadeInScale 1s ease-out;
        }
        
        @keyframes fadeInScale {
            from { opacity: 0; transform: scale(0.95); }
            to { opacity: 1; transform: scale(1); }
        }
        
        /* Heading Styling */
        h2 {
            font-family: 'Orbitron', sans-serif;
            font-size: 2.2rem;
            text-align: center;
            margin-bottom: 2rem;
            background: var(--gradient-animated);
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: text-glow 5s ease-in-out infinite alternate;
        }
        
        @keyframes text-glow {
            0% { filter: hue-rotate(0deg); text-shadow: 0 0 5px var(--primary); }
            100% { filter: hue-rotate(360deg); text-shadow: 0 0 10px var(--accent); }
        }
        
        /* Form Element Styling */
        label {
            display: block;
            font-size: 0.9rem;
            color: var(--text-muted);
            margin-top: 1rem;
            margin-bottom: 0.5rem;
        }
        
        input[type=text], input[type=password], select {
            width: 100%;
            padding: 12px;
            margin-bottom: 1rem;
            background-color: var(--input-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            box-sizing: border-box;
            color: var(--text-light);
            font-size: 1rem;
            transition: all 0.3s ease;
        }
        
        input[type=text]:focus, input[type=password]:focus, select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 10px var(--primary);
        }
        
        button {
            background: var(--gradient-animated);
            color: var(--background-start); /* Dark text on the bright gradient button */
            padding: 14px 20px;
            margin-top: 1.5rem;
            border: none;
            cursor: pointer;
            width: 100%;
            border-radius: 50px;
            font-size: 1.1rem;
            font-weight: 600;
            transition: all 0.3s ease;
            box-shadow: 0 0 15px var(--primary);
        }
        
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 0 25px var(--primary), 0 0 35px var(--secondary);
        }
    </style>
</head>
<body>
    <div class="sparkles"></div>
    
    <div class="container">
        <h2>Wi-Fi Configuration</h2>
        <form action="/save" method="post">
            <label for="ssid">Select Network:</label>
            <select id="ssid" name="ssid">
    )" ;

  // Scan for WiFi networks
  int n = WiFi.scanNetworks();
  if (n == 0) {
    html += "<option value=\"\">No networks found</option>";
  } else {
    for (int i = 0; i < n; ++i) {
      // Add each network to the dropdown
      html += "<option value=\"" + WiFi.SSID(i) + "\">" + WiFi.SSID(i) + "</option>";
      delay(10); // Small delay to allow the ESP to breathe
    }
  }

  html += R"rawliteral(
            </select>
            <label for="manual_ssid">Or Enter Manually (if not listed):</label>
            <input type="text" id="manual_ssid" name="manual_ssid" placeholder="Enter SSID manually">
            <label for="password">Password:</label>
            <input type="password" id="password" name="password">
            <button type="submit">Save</button>
        </form>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function () {
            const sparklesContainer = document.querySelector('.sparkles');
            function createSparkle() {
                const sparkle = document.createElement('div');
                sparkle.classList.add('sparkle');
                const size = Math.random() * 3 + 1;
                sparkle.style.width = `${size}px`;
                sparkle.style.height = `${size}px`;
                sparkle.style.left = `${Math.random() * 100}%`;
                sparkle.style.top = `${Math.random() * 100}%`;
                sparkle.style.animationDelay = `${Math.random() * 5}s`;
                if (sparklesContainer) {
                    sparklesContainer.appendChild(sparkle);
                    setTimeout(() => sparkle.remove(), 5000);
                }
            }
            setInterval(createSparkle, 200);

            // Logic to handle selected SSID vs manual entry
            const ssidSelect = document.getElementById('ssid');
            const manualSsidInput = document.getElementById('manual_ssid');
            const form = document.querySelector('form');

            form.addEventListener('submit', function(event) {
                // If manual SSID is entered, prioritize it
                if (manualSsidInput.value.trim() !== '') {
                    ssidSelect.name = ''; // Disable the select field
                    manualSsidInput.name = 'ssid'; // Enable manual input as the SSID source
                } else {
                    manualSuldInput.name = ''; // Disable manual input
                    ssidSelect.name = 'ssid'; // Enable select as the SSID source
                }
            });
        });
    </script>
</body>
</html>
)rawliteral";
  webServer.send(200, "text/html", html);
}


void handleSave() {
  String ssidToSave;
  if (webServer.hasArg("manual_ssid") && webServer.arg("manual_ssid").length() > 0) {
    ssidToSave = webServer.arg("manual_ssid");
  } else if (webServer.hasArg("ssid")) {
    ssidToSave = webServer.arg("ssid");
  }

  if (!ssidToSave.isEmpty() && webServer.hasArg("password")) {
    String password = webServer.arg("password");
    ssidToSave.toCharArray(deviceConfig.wifi_ssid, 64);
    password.toCharArray(deviceConfig.wifi_password, 64);
    deviceConfig.configured = true;
    saveConfig();
    
    // Stop the web server and signal the main loop to handle the connection
    webServer.stop();
    shouldConnectToNewWifi = true;
    
    webServer.send(200, "text/plain", "Configuration saved! Attempting to connect to new Wi-Fi...");
    delay(100);
  } else {
    webServer.send(400, "text/plain", "Invalid request: SSID or password missing.");
  }
}

void handleNotFound() {
  webServer.send(404, "text/plain", "File Not Found");
}

// New function to handle the connection attempt
void attemptConnect() {
  Serial.println("Attempting to connect to new WiFi...");
  WiFi.disconnect(true);
  delay(100);
  WiFi.mode(WIFI_STA);
  WiFi.begin(deviceConfig.wifi_ssid, deviceConfig.wifi_password);

  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 40) {
    displayConnecting(deviceConfig.wifi_ssid, retries);
    delay(500);
    retries++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("Successfully connected to new Wi-Fi!");
    display.clearDisplay();
    display.setCursor(0, 0);
    display.println("Connected!");
    display.println(WiFi.localIP());
    display.display();
    delay(2000);
  } else {
    Serial.println("Failed to connect to new Wi-Fi. Returning to AP mode.");
    display.clearDisplay();
    display.setCursor(0, 0);
    display.println("Connection Failed.");
    display.println("Returning to AP mode...");
    display.display();
    delay(2000);
    setupAPMode();
  }
  // Reset the flag regardless of success or failure
  shouldConnectToNewWifi = false;
}
