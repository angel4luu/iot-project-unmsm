# Guía de montaje del prototipo

> Esta guía está en español porque el equipo la usa en el banco de pruebas
> (excepción a la regla de documentación en inglés, ver `CLAUDE.md`). La fuente
> de verdad sigue siendo `specs/001-energy-monitoring-system/plan.md`.

## 1. Propósito y estado

Esta guía describe, por etapas, el montaje de un prototipo educativo: un nodo
ESP32-S3 que monitorea un **lazo de 12 V CA** con un foco halógeno de 12 V
(plan B, 2026-11-18). El lazo se alimenta con un adaptador enchufable
certificado, con protección térmica, de 220 V a 12 V CA. El equipo no hace
ningún cableado de red: lo único que se enchufa a 220 V es ese adaptador.

| Elemento | Objetivo del prototipo |
|---|---|
| Circuito observado | Lazo de 12 V CA nominales, 60 Hz, con un foco halógeno de 12 V y unos 20 W |
| Alimentación del lazo y medición de tensión | Adaptador enchufable certificado, con protección térmica y núcleo de hierro, de 220 V CA a 12 V CA, de 2 A o más |
| Medición de corriente | Módulo ACS712ELCTR-20A, versión confirmada de 100 mV/A |
| Rango de medición propuesto | 10–16 V RMS, 55–65 Hz, 0,5–2,0 A RMS |
| Rango aproximado de potencia activa | 0–25 W, rotulado «no validado» |
| Controlador | ESP32-S3 DevKitC-1, ADC1 interno |
| Comunicación | Wi-Fi hacia MQTT sobre TLS/mTLS, configurado aparte |

Los valores de los componentes y la asignación de pines son propuestas nominales
del plan del proyecto. Se verifican en el banco de baja tensión antes de dar el
montaje por definitivo. Esta guía no es una aprobación de instalación, una
certificación ni un procedimiento de facturación.

El prototipo es para una demostración académica. No debe usarse como
dispositivo de protección ni presentarse como apto para una instalación
permanente.

Medir una carga de 220 V queda como trabajo futuro. Si algún día se hace,
vuelven a ser obligatorios el interruptor diferencial de 30 mA, la caja de
ensayo cerrada del ACS712 y la revisión firmada por una persona calificada
(constitución, principio I). Esta guía no cubre ese caso.

## 2. Reglas de seguridad: leer antes de manipular componentes

1. Lo único que se conecta a 220 V es el adaptador certificado. Nunca lo abra,
   lo modifique, corte su cable del lado de 220 V ni use uno dañado, caliente
   o sin certificación.
2. El adaptador entrega corriente **alterna**. Nunca lo enchufe en una entrada de
   alimentación de CC, incluida la entrada jack del Arduino Uno R4.
3. Desenchufe el adaptador antes de cualquier cambio de cableado del lazo o del
   protoboard. Vuelva a enchufarlo solo después de revisar el montaje (etapa 5).
4. El lazo del foco (unos 1,7 A) **nunca** pasa por el protoboard ni por cables
   jumper: va con cable de casa y pinzas cocodrilo (o una regleta) entre los
   tornillos del jack, los tornillos IP+/IP− del ACS712 y el foco.
5. Evite cortocircuitos: ningún conductor pelado debe tocar otro. El adaptador
   tiene protección térmica y se corta si hay un corto, pero un corto calienta
   cables y pinzas; si algo se calienta o huele a quemado, desenchufe.
6. El foco halógeno se calienta mucho: no lo toque encendido ni recién apagado,
   y apóyelo sobre una superficie que no se queme, lejos de papel o plástico.
7. Alimente el nodo con el cargador USB-C certificado. Un cable USB a la
   computadora también es aceptable en este plan, porque todo el montaje es de
   baja tensión.
8. Deténgase si un componente está dañado, se calienta o no corresponde a la
   lista. Regístrelo como pendiente antes de seguir.

## 3. Lista de componentes y herramientas

### Componentes

Cada fila es una pieza o un valor, con su cantidad exacta. «Kit» significa que el
equipo ya lo tiene; confirme la cantidad antes de la compra.

| # | Función | Componente y especificación | Cómo pedirlo | Cant. | Origen |
|---:|---|---|---|---:|---|
| 1 | Controlador y ADC | Espressif ESP32-S3 DevKitC-1, ADC1 interno | `ESP32-S3 DevKitC-1` | 1 | Kit |
| 2 | Sensor de corriente | Módulo Allegro ACS712ELCTR-20A, 100 mV/A, con bornera de tornillos IP+/IP− y pines VCC, OUT, GND | `módulo sensor de corriente ACS712 20A` | 1 | Kit |
| 3 | Alimentación del lazo y sensor de tensión | Adaptador enchufable certificado, **con protección térmica**, de núcleo de hierro; entrada 220 V CA, 60 Hz; salida **12 V CA** (símbolo «~» o «AC OUTPUT»), 2 A o más (24 VA o más); conector cilíndrico, normalmente 5,5 × 2,1 mm. No sirve un cargador de CC ni una fuente conmutada | `adaptador transformador 220V a 12V AC 2A con protección térmica (salida alterna ~)` | 1 | Comprar |
| 4 | Conector del adaptador | Jack DC hembra con bornera de 2 tornillos, del mismo tamaño que el conector del adaptador (**revise el conector antes de comprar**). Rotúlelo «CA» | `jack DC hembra con bornera 5.5x2.1` | 1 | Comprar |
| 5 | Carga de prueba | Foco halógeno G4 de 12 V y 20 W (≈ 1,7 A). Alternativa: foco de auto de 12 V y 21 W (P21W) | `foco halógeno G4 12V 20W` | 1 | Comprar si no hay en casa |
| 6 | Cable del lazo | Cable de casa de cobre de 0,75 mm² (18 AWG) o más, por ejemplo cable mellizo de lámpara: dos tramos de unos 30 cm | — | 2 tramos | Casa |
| 7 | Conexión del foco | Cables cortos con pinzas cocodrilo | `cables con pinzas cocodrilo` | 2 | Kit (confirmar) |
| 8 | Conexión del foco (solo si no hay pinzas) | Regleta de bornes; se usan 2 bornes cortados de la tira | `regleta de bornes 12 polos` | 1 | Comprar solo si falta la fila 7 |
| 9 | Montaje de baja tensión | Protoboard de 830 puntos | `protoboard 830 puntos` | 1 | Kit |
| 10 | Conexiones en el protoboard | Cables jumper macho-macho | `cables jumper macho-macho` | unos 20 | Kit |
| 11 | Conexión del ACS712 y del OLED | Cables jumper macho-hembra (VCC, OUT, GND del ACS712; 4 del OLED si no se inserta en el protoboard) | `cables jumper macho-hembra` | 3–7 | Kit (confirmar) |
| 12 | R1, divisor de tensión | Resistencia 100 kΩ, 1/4 W, 1 % o 5 % | `resistencia 100k 1/4W` | 1 | Comprar |
| 13 | R2 (divisor de tensión) y R3 (divisor de corriente) | Resistencia 4,7 kΩ, 1/4 W | `resistencia 4.7k 1/4W` | 2 | Comprar |
| 14 | Polarización Vb (2) y R4 (divisor de corriente) | Resistencia 10 kΩ, 1/4 W | `resistencia 10k 1/4W` | 3 | Comprar |
| 15 | Resistencias del LED RGB | Resistencia 470 Ω, 1/4 W | `resistencia 470 ohm 1/4W` | 3 | Kit (comprar si faltan) |
| 16 | Resistencia de base del transistor | Resistencia 1 kΩ, 1/4 W | `resistencia 1k 1/4W` | 1 | Kit (comprar si falta) |
| 17 | Condensador de la polarización Vb | Electrolítico 10 µF, 25 V o más (tiene polaridad) | `condensador electrolítico 10uF 25V` | 1 | Comprar |
| 18 | Filtros antialias de GPIO4 y GPIO5 | Cerámico 22 nF (código «223»), 50 V | `condensador cerámico 22nF` | 2 | Comprar |
| 19 | Excitación del zumbador | Transistor NPN 2N2222 o PN2222A (TO-92) | `transistor 2N2222` | 1 | Comprar |
| 20 | Aviso local | Zumbador activo de 5 V (suena solo con tensión continua) | `buzzer activo 5V` | 1 | Kit |
| 21 | Luz de estado | LED RGB de 4 patas, se asume cátodo común | `LED RGB cátodo común 5 mm` | 1 | Kit (confirmar tipo) |
| 22 | Pantalla local | OLED de 0,96", se asume SSD1306 I²C de 4 pines (GND, VCC, SCL, SDA) | `pantalla OLED 0.96 I2C SSD1306` | 1 | Kit (confirmar interfaz) |
| 23 | Alimentación del nodo | Cargador certificado de 5 V y 2 A, y cable con el conector de la placa (USB-C o micro-USB, según su versión) | `cargador USB-C 5V 2A certificado` | 1 | Kit |

**Resumen de compra** (lo que no tiene el kit): adaptador (fila 3) ×1, jack
(fila 4) ×1, foco (fila 5) ×1 si no hay en casa, resistencias 100 kΩ ×1,
4,7 kΩ ×2 y 10 kΩ ×3, condensadores 10 µF ×1 y 22 nF ×2, transistor 2N2222 ×1,
y la regleta solo si no hay pinzas. Las resistencias y condensadores cuestan
céntimos: conviene comprar uno o dos de repuesto de cada valor.

Montaje mínimo (MVP, plan B): solo se listan los componentes necesarios para
medir, indicar localmente y calibrar. No se asume laboratorio ni electricista.
No hacen falta interruptor diferencial, caja de ensayo, fusible ni revisión de
una persona calificada, porque el equipo no cablea nada de 220 V: la protección
térmica del adaptador limita un cortocircuito del lazo.

Lazo del foco: tornillo 1 del jack → cable → IP+ del ACS712 → IP− → foco
(pinzas o regleta) → cable → tornillo 2 del jack. Los mismos tornillos del jack
dan, con dos jumpers, la señal de tensión al protoboard.

Todo el circuito de baja tensión (polarización, divisores, filtros, excitación
del zumbador, LED RGB, OLED y ESP32-S3) se arma en un **protoboard** con cables
jumper, así que no hace falta soldar. Del ACS712 solo van al protoboard sus
pines de baja tensión (5 V, GND y OUT).

No use en este montaje el relé del kit, el Arduino Uno R4, los motores, los
servos ni los sensores no relacionados.

### Herramientas y registros

- Entorno ESP-IDF 5.4 LTS y las instrucciones de compilación y grabación del
  *firmware* del proyecto.
- Destornillador pequeño de punta plana (bornera del jack y tornillos del ACS712).
- Pelacables o, con cuidado, una tijera o cuchilla para pelar los extremos del
  cable del lazo; cinta aislante para cubrir cualquier extremo que sobre.
- No se usa multímetro de referencia (constitución 2.0.0): las tensiones del
  banco (polarización y *offset*) se leen con el propio ADC del ESP32-S3, y las
  lecturas del prototipo se rotulan como «no validadas». Un multímetro básico
  es opcional y solo ayuda a revisar continuidad y valores de resistencias.
- No se asume un osciloscopio: las formas de onda se capturan con el propio ADC
  del ESP32-S3 (registro de muestras crudas por USB en el banco).
- Bitácora de montaje: fecha, operador, identidad de la placa, los sensores, el
  adaptador y el foco, revisión del cableado y del *firmware*, mediciones,
  temperatura e incidencias.

## 4. Trabajo en paralelo: hardware, firmware e integración

El montaje físico, el *firmware* y el servidor no tienen que esperar uno al otro.
Se trabajan en **tres frentes en paralelo**, cada uno con su propia prueba de
salida, y solo después se integran. Los números T### son las tareas de
`specs/001-energy-monitoring-system/tasks.md`.

```
Frente A: hardware (protoboard)      Frente B: firmware            Frente C: servidor
  Etapas 1–4 con apps de prueba        Código de medición probado     Simulador, MQTT, base de
  (foco sin conectar)                  con señales grabadas           datos y Grafana
        │                                    │                              │
        └──────────── Integración 1: firmware completo en la placa ─────────┤
                      (banco, foco sin conectar)                            │
                                     └──── Integración 2: nodo real ─► servidor
                                                      │
                                     Etapa 5: lazo de 12 V y revisión
                                                      │
                                     Etapa 6: sesión con el foco
```

### Frente A: hardware en el protoboard (persona A)

| Paso | Qué se hace | Programa que se usa | Prueba de salida |
|---|---|---|---|
| A1 | Etapa 1: placa sola | App de prueba de la etapa 1 (T027) | La placa arranca, se une al Wi-Fi y el LED RGB cambia de color |
| A2 | Etapa 2: pantalla, zumbador y LED | App de prueba de la etapa 2 (T028) | Texto en el OLED, pitido del zumbador, cada color del LED |
| A3 | Etapas 3 y 4: canales de tensión y corriente | Registrador del ADC (T029) | Vb ≈ 1,65 V con el adaptador desenchufado; *offset* del ACS712 ≈ 1,70 V sin corriente; onda alterna centrada en GPIO4 con el adaptador enchufado |
| A4 | Grabar señales reales | Registrador del ADC (T029), modo captura | Archivos de captura entregados al frente B |

Este frente **no** conecta el foco: el ACS712 se prueba sin
corriente y el adaptador solo alimenta el canal de tensión.

### Frente B: firmware sin la placa (persona B)

El código de medición se escribe y se prueba en la computadora con **señales
grabadas o sintéticas**, sin necesitar el protoboard:

- T033: señales de prueba sintéticas (senoidal en fase, desfasada, con
  *offset*, recortada, con huecos, sin corriente).
- T035–T038: pruebas unitarias de RMS, potencia activa como media de v·i,
  corrección de desfase, energía, calidad y estados de la pantalla y el LED.
- T043–T051: los módulos del *firmware* (adquisición, calibración nominal,
  medición, calidad, punto de control en NVS, cola, MQTT y pantalla).

**Prueba de salida:** `make firmware-test` pasa con todas las señales de prueba,
y también con las capturas reales del paso A4 cuando estén disponibles.

### Frente C: servidor con datos simulados (persona C, o B cuando termine)

- T009–T025 y T052–T058: contratos, simulador, MQTT con mTLS, base de datos,
  servicio de ingesta y Grafana.

**Prueba de salida:** `make acceptance-simulated` muestra en Grafana valores con
unidad, hora, calidad y la etiqueta «no validado», y al menos el 95 % llega en
10 s o menos.

### Integración, en este orden

1. **Integración 1, firmware en la placa (banco, foco sin conectar).** Requiere
   A3 y la prueba de salida de B. Se graba el *firmware* completo en el ESP32-S3
   del protoboard: la pantalla debe mostrar V cerca del valor esperado con el
   adaptador enchufado, corriente cercana a cero y el estado correcto del LED.
2. **Integración 2, nodo real con el servidor (T062).** Requiere la Integración 1
   y la prueba de salida de C. El nodo usa su propio certificado y sus datos
   deben aparecer en Grafana con la etiqueta «no validado». Se prueba también
   apagar el Wi-Fi unos minutos y comprobar que la cola se vacía al volver.
3. **Etapa 5, lazo de 12 V y revisión (T063).** Dos integrantes arman y
   revisan el lazo del foco con el adaptador desenchufado. Sin revisión
   anotada no hay paso 4.
4. **Etapa 6, sesión con el foco (T064, T087).** Calibración nominal, prueba de
   plausibilidad y prueba de alertas (sección 10).

Si una integración falla, se vuelve al frente que corresponde (por ejemplo, un
valor raro de tensión vuelve al frente A o B) y se repite su prueba de salida
antes de integrar de nuevo. Nunca se recablea con el adaptador enchufado.

## 5. Etapa 1: ESP32-S3 por sí solo

Mantenga la placa desconectada de todos los sensores y de todo lo relacionado
con la red.

1. Instale o active el entorno ESP-IDF 5.4 LTS del proyecto.
2. Compile y grabe el *firmware* según las instrucciones del proyecto. Use solo
   la configuración de desarrollo y valores de ejemplo sin secretos donde se
   requiera configuración.
3. Alimente la placa con un cargador USB-C certificado o por USB desde la
   computadora (todo el montaje es de baja tensión).
4. Confirme que la placa arranca y que el diagnóstico serie muestra el destino
   ESP32-S3 y la versión de *firmware* esperados.
5. Configure el Wi-Fi con credenciales locales por la vía de aprovisionamiento
   aprobada. Nunca escriba credenciales en esta guía, en el control de
   versiones, en registros ni en capturas de pantalla.
6. Confirme la conexión a la red Wi-Fi local y anote el resultado sin datos
   sensibles. Los SSID, nombres del broker, direcciones, certificados y claves
   reales no van en este documento.
7. Haga parpadear el LED RGB si ya está conectado de forma segura con sus
   resistencias en serie. Si no lo está, deje esta prueba para la etapa 2.

**Aprobado si:** la placa arranca de forma fiable, el destino del *firmware* es
correcto, el Wi-Fi se conecta sin exponer credenciales y el LED parpadea cuando
está conectado. Resuelva los problemas de arranque o de aprovisionamiento antes
de añadir periféricos.

## 6. Etapa 2: periféricos de baja tensión, uno a la vez

Use el ESP32-S3, el cargador USB-C certificado y una tierra común de baja
tensión. Añada un periférico, pruébelo y apague antes de cambiar el cableado. La
etapa 2 no tiene conexión a la red ni conductor de red en el ACS712.

### OLED: GPIO8 / GPIO9

1. Confirme que el módulo es el SSD1306 I²C de 4 pines asumido. Un OLED SPI de
   7 pines no coincide con esta asignación: deténgase y corrija el plan de pines
   antes de cablear.
2. Conecte SDA a GPIO8, SCL a GPIO9, VCC a 3V3 y GND a la tierra común. Lea las
   etiquetas del módulo: el orden de GND y VCC cambia entre fabricantes.
3. El plan asume que el módulo tiene sus propias resistencias pull-up de I²C. No
   añada pull-ups no previstas sin revisar el módulo y el esquema.
4. Ejecute la prueba de pantalla y muestre una pantalla de estado simple con
   unidades o un texto de prueba. Verifique que se actualiza repetidamente.

**Aprobado si:** se detecta la pantalla I²C esperada y muestra texto estable y
legible.

### Zumbador activo: GPIO16 mediante 2N2222

1. No excite el zumbador de 5 V directamente desde un GPIO del ESP32.
2. Conecte GPIO16 a la base del 2N2222 a través de una resistencia de 1 kΩ.
   Conecte el emisor a la tierra común y el zumbador entre el pin 5V de la placa
   y el colector: la pata «+» (la más larga) del zumbador va a 5V y la «−», al
   colector.
3. Confirme el orden de pines real del transistor en su hoja de datos antes de
   cablear; no es igual en todos los encapsulados.
4. Active brevemente el zumbador desde el *firmware* y confirme que lo conmuta el
   transistor. Apague antes de recablear.

**Aprobado si:** el zumbador suena cuando se le ordena, permanece apagado en otro
caso y el GPIO solo está conectado a través de la resistencia de base.

### LED RGB: GPIO17 / GPIO18 / GPIO21

1. Confirme que el LED es de cátodo común (asumido). En el de cátodo común, la
   pata más larga es el cátodo y va a GND. Si al probar no enciende ningún color,
   puede ser de ánodo común: deténgase y anótelo (cambia el cableado y el
   *firmware*).
2. Conecte rojo a GPIO17, verde a GPIO18 y azul a GPIO21, cada uno con su propia
   resistencia en serie de 470 Ω.
3. Pruebe cada color por separado y luego las indicaciones normal, advertencia,
   medición inválida, sin conexión y datos insuficientes del mapa de estados
   local.

**Aprobado si:** cada canal enciende por separado, los colores combinados se
distinguen y ningún canal está conectado sin su resistencia de 470 Ω.

Anote el resultado de cada periférico antes de continuar. Si una prueba falla,
retire ese periférico y vuelva a la última configuración que funcionaba.

## 7. Etapa 3: canal de tensión en el banco de baja tensión

Esta etapa usa solo la salida del adaptador CA-CA certificado y aislado. El
adaptador no se conecta a ninguna entrada de alimentación de CC. No pase ningún
conductor por el ACS712 en esta etapa: el foco todavía no se conecta.

### Circuito nominal

- Enchufe el conector del adaptador en el jack DC hembra con bornera y lleve
  dos cables jumper desde sus tornillos al protoboard; no se corta ningún cable.
  Mantenga el adaptador desenchufado del tomacorriente mientras
  cablea.
- Lleve el pin 3V3 y un pin GND de la placa a las líneas de alimentación del
  protoboard.
- Arme el nodo de polarización de 1,65 V (Vb): dos resistencias iguales de
  10 kΩ en serie entre 3V3 y GND, con el condensador de 10 µF de Vb a GND. El
  electrolítico tiene polaridad: la pata «+» (la larga) va a Vb y la marcada
  con la franja «−», a GND.
- Conecte un cable de salida del adaptador directamente a Vb. La salida del
  adaptador está aislada (flotante), así que esto solo referencia la señal
  alterna a 1,65 V. Este diseño no lleva condensador de acoplamiento en serie.
- Conecte el otro cable del adaptador a través de R1 = 100 kΩ al punto A, y
  R2 = 4,7 kΩ desde A de vuelta a Vb. Así, A queda en
  Vb + v_adaptador × 4,7/104,7 (un divisor de aproximadamente 1/22).
- Conecte A a GPIO4 (ADC1_CH3) y coloque 22 nF de A a GND como filtro
  antialias. Esto coincide con la Fig. 2 del artículo y con plan.md › Front end.
- Una las tierras de baja tensión como en el esquema revisado. La salida del
  adaptador y el circuito del ESP32 quedan solo en el lado aislado de baja
  tensión.

### Verificaciones

1. Con el adaptador desenchufado y la placa alimentada por su cargador USB-C
   certificado, lea con el ADC del ESP32-S3 la tensión en GPIO4: sin señal del
   adaptador, GPIO4 queda en Vb a través de R2. Debe estar cerca de 1,65 V. Anote el valor real; si no lo está, revise el divisor, una conexión
   invertida de tierra o 3V3, o el cableado del condensador antes de seguir.
2. Con el adaptador desenchufado, confirme que GPIO4 está dentro del rango
   seguro del ADC y centrado cerca de la polarización medida. No conecte la red
   de resistencias a un GPIO hasta revisar el cableado en busca de
   cortocircuitos y tensiones fuera de rango.
3. Enchufe el adaptador certificado en un tomacorriente común solo después
   de revisar el cableado de baja tensión. Capture la forma de onda en GPIO4 y
   confirme una oscilación alterna centrada.
4. Para el adaptador de 12 V CA, el plan estima unos ±0,76 V de pico en GPIO4 con
   12 V RMS y como máximo unos ±1,1 V aun si en vacío entrega unos 18 V RMS. Tómelo solo como una
   oscilación esperada aproximada; verifique en el banco el adaptador real y la
   forma de onda del ADC.
5. Confirme que la forma de onda permanece en el rango lineal del ADC y no se
   recorta. Si se recorta, deténgase y cambie el divisor solo mediante un cambio
   documentado y revisado del esquema. No improvise valores.

**Aprobado si:** Vb está cerca de 1,65 V con el adaptador desenchufado, el
adaptador produce en GPIO4 una forma de onda periódica centrada y no se observan
recortes ni tensiones inseguras. Anote la identidad del adaptador, su salida, la
forma de onda y la polarización medida.

## 8. Etapa 4: canal de corriente sin corriente

Esta etapa verifica solo la salida de baja tensión del ACS712, sin corriente.
Ningún conductor pasa por IP+/IP−. La polaridad se comprueba después, en la
primera medición con el foco (etapa 6).

### Circuito nominal y verificaciones

1. Con tres jumpers macho-hembra, conecte VCC del módulo ACS712 al pin 5V de la
   placa (que recibe los 5 V del cargador), GND a la tierra común y OUT al
   divisor del paso 2. El módulo tiene su propio condensador de desacoplo.
2. Pase la salida OUT del módulo por el divisor propuesto R3 = 4,7 kΩ y
   R4 = 10 kΩ. La carga total es de 14,7 kΩ, mayor que el mínimo de 4,7 kΩ del
   ACS712. El divisor lleva la salida del sensor a un rango seguro de 3,3 V para
   el ADC.
3. Coloque 22 nF de GPIO5 (ADC1_CH4) a GND. Mantenga cortos el punto de salida y
   las conexiones de tierra, y revise el esquema antes de energizar.
4. Sin corriente por el sensor, lea la salida dividida en GPIO5. El valor
   nominal esperado es de unos 1,70 V, que corresponde al punto medio de unos
   2,5 V del ACS712 reducido al rango seguro del ESP32. Anote el *offset* medido;
   no sustituye la captura de cero de 60 s de cada sesión posterior.
5. Deténgase si GPIO5 sale del rango seguro del ADC o el valor es inestable.

**Aprobado si:** GPIO5 está cerca de 1,70 V sin corriente, estable y dentro del
rango del ADC. En esta etapa el foco no está conectado.

## 9. Etapa 5: lazo de 12 V y revisión del montaje

Con el adaptador **desenchufado**, arme el lazo del foco y revíselo antes de
enchufar. No hace falta una persona calificada porque no hay cableado de red,
pero la revisión la hacen dos integrantes del equipo y se anota.

1. Pele unos 8 mm de cada extremo de los dos tramos de cable de casa.
2. Tramo 1: del tornillo 1 del jack al tornillo IP+ del ACS712. Ajuste ambos
   tornillos.
3. Del tornillo IP− del ACS712 a una pata del foco, con una pinza cocodrilo (o
   con un borne de la regleta). Las patas del G4 son finas: muerda cada pata
   con su pinza sin que las dos pinzas se toquen. Con un foco de auto, una
   pinza va al contacto de la base y la otra al casquillo metálico.
4. Tramo 2: de la otra pata del foco (pinza o regleta) al tornillo 2 del jack.
   Como el lazo es de CA, da igual qué tornillo del jack es el 1 o el 2.
5. Los dos jumpers de tensión siguen saliendo de los mismos tornillos del jack
   hacia el protoboard, como en la etapa 3.

Lista de revisión (marque cada punto):

- El adaptador es certificado, con protección térmica, salida CA y sin daños.
- El lazo no pasa por el protoboard ni por cables jumper.
- Los tornillos del jack y del ACS712 están firmes; no hay hilos sueltos.
- Ningún conductor pelado puede tocar a otro; las pinzas no se tocan entre sí.
- El foco está sobre una superficie que no se quema y lejos del protoboard.
- El ACS712 recibe 5 V, GND y OUT por jumpers, como en la etapa 4.

### Registro de la revisión

| Campo | Valor |
|---|---|
| Revisión del cableado | Por completar |
| Adaptador (marca, salida, protección térmica) | Por completar |
| Foco (tipo y potencia de placa) | Por completar |
| Revisado por (dos integrantes) | Por completar |
| Fecha | Por completar |
| Temas pendientes | Por completar |

## 10. Etapa 6: sesión con el foco, calibración nominal y alertas

Esta etapa se realiza cuando la etapa 5 está completa. Cualquier cambio de
cableado se hace con el adaptador desenchufado.

### Montaje de ensayo

```
Tomacorriente 220 V ─► Adaptador 12 V CA (protección térmica) ─► jack
  jack ─► jumpers ─► protoboard ─► GPIO4                     (tensión del lazo)
  jack ─► cable ─► ACS712 IP+ … IP− ─► foco 12 V ─► cable ─► jack
                   └─► 5 V, GND, OUT ─► protoboard ─► GPIO5
ESP32-S3 (cargador USB-C) ─► Wi-Fi ─► servidor ─► panel
```

No se usa multímetro de referencia: el prototipo funciona con coeficientes
nominales y sus lecturas se rotulan como «no validadas» (constitución 2.0.0).

1. Registre la revisión del montaje, el *commit* del *firmware*, la
   configuración del ADC, el adaptador, el modelo y versión del ACS712, el
   operador, las condiciones ambientales, el foco y su potencia de placa, y que
   no se usó instrumento de referencia.
2. Cargue los coeficientes nominales: ganancia de tensión solo según R1/R2 (el
   nodo mide directamente los ~12 V del adaptador), ganancia de corriente según
   100 mV/A y R3/R4, y corrección de fase según el desfase conocido de una
   conversión entre canales.
3. Con el foco desconectado de una de sus pinzas, enchufe el adaptador,
   caliente el sistema al menos 10 minutos y capture 60 segundos de corriente
   cero para guardar el *offset* del ACS712. Repita el autocero antes de cada
   sesión.
4. Desenchufe, conecte la pinza del foco y vuelva a enchufar. La potencia debe
   salir positiva: eso confirma la polaridad del ACS712. Si sale negativa,
   corrija el signo en los coeficientes; no recablee. Con el foco de 20 W, GPIO5
   oscila unos ±0,16 V de pico alrededor de 1,70 V. Guarde el resultado como
   revisión de calibración `nominal`, congélela y regístrela en el servidor.
5. Prueba de plausibilidad (E1): con el foco encendido, la tensión debe estar
   entre 10 y 16 V, la potencia debe ser positiva y quedar dentro de ±20 % de
   la potencia de placa (por ejemplo, 16–24 W para un foco de 20 W). Registre al
   menos 5 minutos encendido y 1 minuto apagado; apagado, la corriente debe
   quedar en el límite absoluto de ruido.
6. Prueba de alertas (E2): configure un límite de unos 15 W. Con el foco
   encendido debe aparecer la alerta local y en el panel; al apagarlo debe
   despejarse. El pico de arranque del filamento frío dura milisegundos y no
   debe disparar la alerta, porque se exige confirmación sostenida. Repita con
   el servidor detenido para comprobar el aviso local.
7. Conserve extractos de la forma de onda cruda, resúmenes, *scripts*, entorno,
   coeficientes, revisiones de *firmware* y cableado, *hashes* y la tabla de
   plausibilidad. Marque los datos fuera de rango.

La prueba de plausibilidad describe solo la configuración probada del prototipo
educativo; no es una afirmación de exactitud.

## 11. Solución de problemas

| Síntoma | Causa probable | Verificación |
|---|---|---|
| El ESP32-S3 no arranca | Destino o compilación incorrectos, alimentación o grabación | Revise la identidad de la placa, el cargador y cable USB-C, la salida de compilación y el registro de arranque |
| El Wi-Fi no se conecta | Credenciales locales o configuración de la red Wi-Fi local | Verifique el aprovisionamiento localmente; nunca copie secretos en registros ni en esta guía |
| El OLED no muestra nada | Módulo SPI, SDA/SCL invertidos, alimentación o dirección/configuración | Confirme el supuesto de I²C de 4 pines; revise GPIO8/9, 3V3, GND y la configuración del *firmware* |
| El zumbador no suena o no se apaga | Orden de pines del transistor, resistencia de base o cableado | Apague; verifique el orden de pines del 2N2222, GPIO16–1 kΩ–base, emisor a GND y el camino zumbador/colector |
| Falta un color del RGB | Tipo de LED u orden de pines, o falta la resistencia en serie | Confirme el supuesto de cátodo común y el mapa GPIO17/18/21; verifique cada resistencia de 470 Ω |
| Vb no está cerca de 1,65 V | Error en el divisor de polarización, la tierra o el condensador de 10 µF | Con el adaptador desenchufado, lea Vb y revise el divisor de dos 10 kΩ |
| La señal en GPIO4 se recorta | El divisor o la salida del adaptador difieren del valor nominal | Deténgase; anote la forma de onda y el adaptador; cambie solo mediante un cambio documentado del esquema |
| No hay oscilación en GPIO4 | Adaptador desenchufado, jumper suelto en la bornera o el protoboard, o error en R1/R2/Vb | Confirme que el adaptador es de salida CA, ajuste los tornillos del jack, reinserte los jumpers y revise el esquema |
| El foco no enciende | Tornillo flojo, pinza suelta, foco quemado o protección térmica del adaptador activada | Desenchufe; revise el lazo punto por punto; si el adaptador está caliente, espere a que se enfríe y busque un corto |
| El adaptador se apaga o se calienta | Cortocircuito en el lazo o foco de más de 24 W | Desenchufe; busque conductores pelados que se toquen; use un foco de 20 W |
| El *offset* en GPIO5 está lejos de ~1,70 V | Alimentación del ACS712, divisor, tierra o versión del sensor | Verifique 5 V, tierra común, R3 = 4,7 kΩ, R4 = 10 kΩ y que el módulo sea el de 20 A |
| La potencia activa sale negativa | Sentido del cable en IP+/IP− | Corrija el signo en los coeficientes; no hace falta recablear |
| La potencia queda fuera de ±20 % | Tensión del adaptador con carga distinta de 12 V, coeficiente equivocado o foco distinto al rotulado | Revise la tensión medida, los coeficientes y la placa del foco; anote el resultado tal como salió |
| Los valores del ADC saltan o se pierden muestras | Ruido de cableado, configuración del ADC, desbordamiento de DMA o conversión faltante | Revise tierras y filtros y el diagnóstico del *firmware*; las ventanas afectadas son inválidas |

## 12. Temas pendientes y supuestos

- Se asume que el OLED es un módulo SSD1306 I²C de 4 pines. Confirme el módulo
  real; una pantalla SPI de 7 pines cambia la asignación de pines.
- Se asume que el LED RGB es de cátodo común. Confirme su tipo y orden de pines
  antes de conectar GPIO17/18/21.
- No hay multímetro de referencia (constitución 2.0.0). Si más adelante el
  equipo consigue uno True RMS, puede añadirse una calibración `reference` sin
  cambiar el circuito.
- Adaptador y foco por comprar. Verifique la certificación, la salida CA, la
  protección térmica y que la corriente nominal sea de 2 A o más.
- Confirme en el kit: 2 cables con pinzas cocodrilo, 3–7 jumpers macho-hembra,
  3 resistencias de 470 Ω y 1 de 1 kΩ. Compre solo lo que falte (la regleta
  reemplaza a las pinzas).
- El ESP32-S3 DevKitC-1 es ancho y en un protoboard de 830 puntos puede dejar
  libre una sola fila de agujeros por lado (o ninguna). Si no quedan agujeros
  libres para un pin que se necesita, conecte ese pin con un jumper
  macho-hembra directo al pin de la placa.
- Los pines del ADC, la atenuación y los parámetros exactos de calibración del
  *firmware* se confirman en el banco.
- La calibración nominal y la tabla de plausibilidad deben completarse antes de
  mostrar cualquier medición, siempre rotulada como «no validada».
- Trabajo futuro: una sesión con una carga de 220 V exige interruptor
  diferencial de 30 mA, caja de ensayo cerrada del ACS712 y revisión firmada por
  una persona calificada.
