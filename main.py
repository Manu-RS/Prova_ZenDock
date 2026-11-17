# Gruppo 22
from machine import Pin, I2C
import dht
import time

# Driver e librerie hardware dal repository ZenDock
from driver.ssd1306 import SSD1306_I2C
from sensors import Ldr, Potentiometer, Led, Servo, StepMotor, Buzzer

# ==========================================
# CONFIGURAZIONE HARDWARE (PIN ESP32)
# ==========================================
PIN_DHT22     = 4
PIN_LDR       = 34
PIN_POT       = 35
PIN_SERVO     = 18
PIN_STEPPER   = [16, 17, 19, 23]
PIN_OLED_SDA  = 21
PIN_OLED_SCL  = 22
PIN_BTN1      = 32
PIN_BTN2      = 33
PIN_LED_VERDE = 25
PIN_LED_ROSSO = 26
PIN_BUZZER    = 27


class GreenhouseSystem:
    def __init__(self):
        # Inizializzazione Interfaccia I2C e Display OLED
        self._i2c = I2C(0, scl=Pin(PIN_OLED_SCL), sda=Pin(PIN_OLED_SDA))
        self._oled = SSD1306_I2C(128, 64, self._i2c)
        
        # Inizializzazione Sensori
        self._dht = dht.DHT22(Pin(PIN_DHT22))
        self._ldr = Ldr(PIN_LDR)
        self._potenziometro = Potentiometer(PIN_POT)
        
        # Inizializzazione Attuatori
        self._servo = Servo(PIN_SERVO)
        self._stepper = StepMotor(PIN_STEPPER, delay=0.002, half_step=True)
        self._led_verde = Led(PIN_LED_VERDE)
        self._led_rosso = Led(PIN_LED_ROSSO)
        self._buzzer = Buzzer(PIN_BUZZER)
        
        # Inizializzazione Pulsanti
        self._btn1 = Pin(PIN_BTN1, Pin.IN, Pin.PULL_UP)
        self._btn2 = Pin(PIN_BTN2, Pin.IN, Pin.PULL_UP)
        
        # Stati e Variabili Operative
        self._modalita_auto = True
        self._temperatura = 0.0
        self._umidita = 0.0
        self._luminosita = 0.0
        
        self._soglia_temp = 25
        self._soglia_servo = 0
        
        self._tenda_pos = 0  # 0=Aperta, 1=Intermedia, 2=Chiusa
        self._finestra_aperta = False
        
        # Stati di Allarme
        self._allarme_attivo = False
        self._buzzer_silenziato = False
        self._causa_allarme = ""
        
        # Contatori e Flag Temporali
        self._ultimo_dht = 0
        self._ultimo_oled = 0
        self._ultimo_buzzer_toggle = 0
        self._buzzer_stato = False
        self._ultimo_btn1 = 0
        self._ultimo_btn2 = 0
        self._richiesta_tenda_manuale = False
        
        # Assegnazione Interrupt Pulsanti
        self._btn1.irq(trigger=Pin.IRQ_FALLING, handler=self._btn1_isr)
        self._btn2.irq(trigger=Pin.IRQ_FALLING, handler=self._btn2_isr)
        
        # Impostazione Iniziale
        self._led_verde.on()
        self._led_rosso.off()
        self._servo.set_angle(0)
        self._stepper.turn_off()

    # ISR Pulsante 1: Alterna la modalità Operativa
        # Sostituisci i metodi di gestione interrupt nel tuo main.py con questi:

    # ISR Pulsante 1: Alterna la modalità Operativa
    # Nelle ISR non creiamo array, non usiamo print. Impostiamo solo flag.
    def _btn1_isr(self, pin):
        ora = time.ticks_ms()
        if time.ticks_diff(ora, self._ultimo_btn1) > 250:
            # self._modalita_auto è un semplice booleano (non alloca memoria)
            self._modalita_auto = not self._modalita_auto
            self._buzzer_silenziato = False
            self._ultimo_btn1 = ora

    # ISR Pulsante 2: Silenzia allarme in AUTO, sposta tenda in MANUALE
    def _btn2_isr(self, pin):
        ora = time.ticks_ms()
        if time.ticks_diff(ora, self._ultimo_btn2) > 250:
            if self._modalita_auto:
                self._buzzer_silenziato = True
                self._buzzer.stop()
            else:
                # Impostiamo solo un flag, il movimento effettivo avverrà
                # nel loop principale tramite gestisci_tenda()
                self._richiesta_tenda_manuale = True
            self._ultimo_btn2 = ora

    # Aggiorna i valori dei sensori ciclicamente e senza bloccare
    def aggiorna_sensori(self):
        ora = time.ticks_ms()
        if time.ticks_diff(ora, self._ultimo_dht) >= 2000:
            try:
                self._dht.measure()
                self._temperatura = self._dht.temperature()
                self._umidita = self._dht.humidity()
            except Exception:
                pass
            self._ultimo_dht = ora
            
        self._luminosita = 100 - self._ldr.read_percentage() 

        if self._modalita_auto:
            self._soglia_temp = self._potenziometro.read_range(22, 32)
        else:
            self._soglia_servo = self._potenziometro.read_range(0, 90)

    # Regola la finestra in base all'isteresi (AUTO) o al potenziometro (MANUALE)
    def gestisci_ventilazione(self):
        if self._modalita_auto:
            if self._temperatura > self._soglia_temp and not self._finestra_aperta:
                self._servo.set_angle(90)
                self._finestra_aperta = True
            elif self._temperatura <= (self._soglia_temp - 2) and self._finestra_aperta:
                self._servo.set_angle(0)
                self._finestra_aperta = False
        else:
            self._servo.set_angle(self._soglia_servo)
            self._finestra_aperta = (self._soglia_servo > 0)

    # Determina e raggiunge la posizione ottimale della schermatura (0, 1, 2)
    def gestisci_tenda(self):
        target_pos = self._tenda_pos
        
        if self._modalita_auto:
            if self._luminosita <= 30:
                target_pos = 0
            elif self._luminosita <= 70:
                target_pos = 1
            else:
                target_pos = 2
        else:
            if self._richiesta_tenda_manuale:
                target_pos = (self._tenda_pos + 1) % 3
                self._richiesta_tenda_manuale = False

        if target_pos != self._tenda_pos:
            diff = target_pos - self._tenda_pos
            gradi = diff * 90
            direzione = StepMotor.CW if gradi > 0 else StepMotor.CCW
            
            self._stepper.rotate_degrees(abs(gradi), direction=direzione)
            self._tenda_pos = target_pos

    # Esamina le condizioni critiche e attiva/disattiva le notifiche audio e visive
    def gestisci_allarmi(self):
        allarmi = []
        if self._temperatura > 35.0:
            allarmi.append("TEMP")
        if self._umidita < 35.0:
            allarmi.append("UMID")
            
        self._allarme_attivo = len(allarmi) > 0
        
        if self._allarme_attivo:
            self._causa_allarme = " + ".join(allarmi)
            self._led_verde.off()
            
            ora = time.ticks_ms()
            if time.ticks_diff(ora, self._ultimo_buzzer_toggle) > 500:
                self._buzzer_stato = not self._buzzer_stato
                self._ultimo_buzzer_toggle = ora
                
                if self._buzzer_stato:
                    self._led_rosso.on()
                    if not self._buzzer_silenziato:
                        self._buzzer.play_tone_async(400, frequency=1000)
                else:
                    self._led_rosso.off()
        else:
            self._causa_allarme = ""
            self._led_verde.on()
            self._led_rosso.off()
            self._buzzer.stop()
            self._buzzer_silenziato = False

    # Scrive i dati di monitoraggio formattati sul display OLED
    def aggiorna_display(self):
        ora = time.ticks_ms()
        if time.ticks_diff(ora, self._ultimo_oled) >= 500:
            self._oled.fill(0)
            
            # Intestazione
            self._oled.text("GREENMARS", 0, 0)
            mod_txt = "AUTO" if self._modalita_auto else "MANUALE"
            self._oled.text(mod_txt, 128 - len(mod_txt) * 8, 0)
            self._oled.hline(0, 9, 128, 1)
            
            # Parametri Ambientali
            self._oled.text(f"TEMP: {self._temperatura:.1f} C", 0, 12)
            self._oled.text(f"UMID: {self._umidita:.1f} %", 0, 20)
            self._oled.text(f"LUCE: {self._luminosita:.0f} %", 0, 28)
            
            # Stato Attuatori
            stato_vent = "APERTA" if self._finestra_aperta else "CHIUSA"
            self._oled.text(f"VENT: {stato_vent}", 0, 36)
            
            stati_tenda = {0: "APERTA", 1: "PARZIALE", 2: "CHIUSA"}
            self._oled.text(f"TENDA: {stati_tenda[self._tenda_pos]}", 0, 44)
            
            # Sistema e Allarmi
            if self._allarme_attivo:
                self._oled.text(f"ALRM: {self._causa_allarme}", 0, 56)
            else:
                self._oled.text("SISTEMA OK", 0, 56)
                
            self._oled.show()
            self._ultimo_oled = ora

    # Ciclo di vita principale
    def run(self):
        # Prima lettura per evitare valori "0.0" all'avvio
        try:
            self._dht.measure()
            self._temperatura = self._dht.temperature()
            self._umidita = self._dht.humidity()
        except:
            pass


        while True:
            self.aggiorna_sensori()
            self.gestisci_ventilazione()
            self.gestisci_tenda()
            self.gestisci_allarmi()
            self.aggiorna_display()
            time.sleep_ms(10)


if __name__ == '__main__':
    serra = GreenhouseSystem()
    serra.run()