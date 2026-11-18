# Guía de montaje del prototipo

> Esta guía está en español porque el equipo la usa en el banco de pruebas
> (excepción a la regla de documentación en inglés, ver `CLAUDE.md`). La fuente
> de verdad sigue siendo `specs/001-energy-monitoring-system/plan.md`.

## 1. Propósito y estado

Esta guía describe, por etapas, el montaje de un prototipo educativo: un nodo
ESP32-S3 que monitorea una carga monofásica conectada a un tomacorriente común protegido por un interruptor diferencial de 30 mA.

| Elemento | Objetivo del prototipo |
|---|---|
| Red observada | 220 V CA nominales, 60 Hz |
| Medición de tensión | Adaptador enchufable certificado y aislado, de 220 V CA a 9–15 V CA |
| Medición de corriente | Módulo ACS712ELCTR-20A, versión confirmada de 100 mV/A |
| Rango de medición propuesto | 180–250 V RMS, 55–65 Hz, 0,5–5,0 A RMS |
| Rango aproximado de potencia activa | 0–1100 W, solo después de calibrar |
| Controlador | ESP32-S3 DevKitC-1, ADC1 interno |
| Comunicación | Wi-Fi hacia MQTT sobre TLS/mTLS, configurado aparte |

Los valores de los componentes y la asignación de pines son propuestas nominales
del plan del proyecto. Se verifican en el banco de baja tensión y se confirman en
la revisión del esquema antes de dar el montaje por definitivo. Esta guía no es
una aprobación de instalación, una certificación, un procedimiento de
facturación ni un permiso para conectar una carga.

El prototipo es para una demostración académica supervisada. No debe usarse como
dispositivo de protección ni presentarse como apto para una instalación
permanente.

## 2. Reglas de seguridad: leer antes de manipular componentes

1. El ACS712 es el único componente del prototipo cuyos terminales llevan la
   corriente de la red. Va solo dentro de la **caja de ensayo**: una caja cerrada,
   que impida el contacto y sea retardante de llama. Solo sus pines de baja
   tensión salen de esa caja.
2. Nunca coloque el camino de red del ACS712 sobre un protoboard ni use cables
   de red sueltos o expuestos. Use terminales y conductores de la capacidad
   adecuada, terminales cubiertos, sujeción de cables y la caja de ensayo revisada.
3. Nunca manipule, cablee, ajuste ni mida el ACS712 o su camino de red con el
   circuito energizado. Desenergice y verifique antes de cualquier cambio físico.
4. El tomacorriente de prueba debe estar protegido por un interruptor
   diferencial de 30 mA: el del tablero eléctrico del edificio (marcado "30 mA",
   con botón de prueba "T"), si existe, o un protector diferencial portátil
   certificado que se enchufa en la pared. Pruébelo con su botón antes de cada
   sesión. La protección contra sobrecorriente es la llave termomagnética
   existente de ese circuito, solo si la persona revisora confirma que el cable
   de prueba, los terminales y el módulo ACS712 soportan su capacidad.
5. Una persona calificada debe revisar el esquema, la capacidad de los
   componentes, el aislamiento, las distancias de fuga y de aislamiento en aire,
   la sección de los conductores, la caja de ensayo, las protecciones y el montaje de
   prueba, y firmar el registro de revisión antes de cualquier conexión a la red.
6. No conecte el USB a una computadora conectada a tierra de la red mientras el
   prototipo esté energizado, salvo que la persona revisora apruebe
   explícitamente ese arreglo. Por defecto, alimente el nodo con el cargador
   USB-C certificado.
7. El adaptador CA-CA tiene salida de corriente **alterna** y se usa para medir.
   Nunca lo enchufe en una entrada de alimentación de CC, incluida la entrada
   jack del Arduino Uno R4. Su conector se enchufa en un jack DC hembra con
   bornera, rotulado "CA", y de sus dos tornillos salen dos cables jumper al
   protoboard, a la red de medición de tensión descrita aquí.
8. Las etapas 1 a 4 son trabajo desenergizado o en baja tensión. La etapa 6 solo
   se permite después de la revisión firmada, en el montaje controlado y
   supervisado. Nunca trabaje con tensión ni deje terminales energizados
   expuestos.
9. Deténgase de inmediato si un componente, conductor, caja de ensayo, barrera de
   aislamiento o capacidad de protección es desconocido o está dañado. Regístrelo
   como pendiente y deje que la persona revisora decida el siguiente paso seguro.

## 3. Lista de componentes y herramientas

### Componentes

La lista sigue el plan del proyecto. "Comprar" y "por confirmar" son notas de
estado, no una autorización para sustituir componentes sin revisión.

| Función | Componente y detalle nominal | Cómo pedirlo | Cant. | Estado / origen |
|---|---|---|---:|---|
| Controlador y ADC | Espressif ESP32-S3 DevKitC-1, ADC1 interno | `ESP32-S3 DevKitC-1` | 1 | Kit; disponible |
| Sensor de corriente | Módulo Allegro ACS712ELCTR-20A, 100 mV/A | `módulo sensor de corriente ACS712 20A` | 1 | Kit; disponible |
| Sensor de tensión | Adaptador enchufable certificado y aislado, 220 V CA a 9–15 V CA | `adaptador transformador 220V a 12V AC (salida alterna ~)` | 1 | Comprar |
| Conector del adaptador | Jack DC hembra con bornera de tornillos, del mismo tamaño que el conector del adaptador (normalmente 5,5 × 2,1 mm; **revise el conector**) | `jack DC hembra con bornera 5.5x2.1` | 1 | Comprar; bajo costo |
| Montaje de baja tensión | Protoboard y cables jumper macho-macho (solo circuitos de baja tensión) | `protoboard 830 puntos`; `cables jumper macho-macho` | 1 juego | Kit; disponible |
| Resistencias de divisores y polarización | 1/4 W: 100 kΩ, 4,7 kΩ ×2, 10 kΩ ×3 | `resistencias 1/4 W 100k, 10k, 4.7k` | 1 juego | Comprar; bajo costo |
| Condensadores de polarización y filtro | 10 µF ×1 y 22 nF ×2 | `condensador electrolítico 10uF 25V`; `condensador cerámico 22nF` | 1 juego | Comprar; bajo costo |
| Aviso local | Zumbador activo de 5 V | `buzzer activo 5V` | 1 | Kit; disponible |
| Luz de estado | LED RGB, se asume cátodo común, con 3 × 470 Ω | `LED RGB cátodo común 5 mm` | 1 | Kit; confirmar tipo |
| Pantalla local | OLED de 0,96", se asume SSD1306 I²C de 4 pines | `pantalla OLED 0.96 I2C SSD1306` | 1 | Kit; confirmar interfaz |
| Excitación del zumbador | Transistor NPN 2N2222 o PN2222A y resistencia de base de 1 kΩ | `transistor 2N2222`; `resistencia 1k 1/4 W` | 1 c/u | Comprar; bajo costo |
| Alimentación del nodo | Cargador USB-C certificado de 5 V, 2 A, y cable | `cargador USB-C 5V 2A certificado` | 1 | Kit; disponible |
| Caja de ensayo del ACS712 | Caja plástica cerrada, retardante de llama, **solo para el ACS712**, armada como una extensión de medición: enchufe y cable con prensaestopa, ACS712 en la fase y un tomacorriente para la carga. La arma o revisa la persona calificada | `caja de paso plástica`; `prensaestopa`; `enchufe y tomacorriente` | 1 juego | Comprar |
| Protección diferencial | Interruptor diferencial de 30 mA que proteja el tomacorriente de prueba: el del tablero del edificio si existe; si no, un protector diferencial portátil certificado | `protector diferencial portátil 30 mA para enchufe` (solo si el tablero no tiene uno) | 0–1 | Edificio o comprar; revisar el tablero |
| Cargas de prueba | Cargas resistivas domésticas: foco incandescente o halógeno de 100 W; reflector halógeno de unos 500 W; plancha o calefactor de unos 1000 W (placa ≤ 1,1 kW). Además, una carga inductiva (ventilador pequeño) o no lineal (lámpara LED o cargador) estable | `foco halógeno 100 W`; `reflector halógeno 500 W`; `plancha 1000 W` | 3–4 | Del equipo o comprar; revisar la placa de cada carga |

Montaje mínimo (MVP): solo se listan los componentes necesarios para medir,
indicar localmente, proteger y calibrar. No se asume ningún laboratorio: las
pruebas con red se hacen desde un tomacorriente común de 220 V, **siempre**
protegido por un interruptor diferencial de 30 mA. Tampoco hay una persona
calificada provista por un laboratorio: el equipo debe convocar a un
electricista con licencia (o a un docente de ingeniería eléctrica) para revisar
la caja de ensayo del ACS712 y el montaje de prueba, y firmar la revisión antes de
cualquier conexión a la red.

Todo el circuito de baja tensión (polarización, divisores, filtros, excitación
del zumbador, LED RGB, OLED y ESP32-S3) se arma en un **protoboard** con cables
jumper, así que no hace falta soldar. El lado de red del ACS712 nunca va en el
protoboard: solo salen de su caja de ensayo cerrada sus pines de baja tensión
(5 V, GND y OUT). El protoboard y el ESP32-S3 quedan fuera de esa caja.

No use en este montaje el relé del kit, el Arduino Uno R4, los motores, los
servos ni los sensores no relacionados. La entrada jack del Arduino Uno R4 no es
una entrada para el adaptador de CA. Este diseño no incluye ninguna placa propia
de medición conectada directamente a la red.

### Herramientas y registros

- Entorno ESP-IDF 5.4 LTS y las instrucciones de compilación y grabación del
  *firmware* del proyecto.
- Herramientas de mano aisladas, adecuadas para el montaje en baja tensión.
- No se usa multímetro de referencia (constitución 2.0.0): las tensiones del
  banco (polarización y *offset*) se leen con el propio ADC del ESP32-S3, y las
  lecturas del prototipo se rotulan como «no validadas». Un multímetro básico
  es opcional y solo ayuda a revisar continuidad y valores de resistencias.
- No se asume un osciloscopio: las formas de onda se capturan con el propio ADC
  del ESP32-S3 (registro de muestras crudas por USB en el banco, antes de
  cualquier etapa con red).
- Protoboard y cables jumper para todo el circuito de baja tensión; no se
  requiere soldar.
- Destornillador pequeño (bornera del jack) y herramientas para perforar la
  caja de ensayo (prensaestopa); nada de cableado de red en protoboard ni con
  cables expuestos.
- Bitácora de montaje: fecha, operador, identidad de la placa y los sensores,
  revisión del cableado y del *firmware*, identidad del instrumento, mediciones,
  temperatura e incidencias.

## 4. Trabajo en paralelo: hardware, firmware e integración

El montaje físico, el *firmware* y el servidor no tienen que esperar uno al otro.
Se trabajan en **tres frentes en paralelo**, cada uno con su propia prueba de
salida, y solo después se integran. Los números T### son las tareas de
`specs/001-energy-monitoring-system/tasks.md`.

```
Frente A: hardware (protoboard)      Frente B: firmware            Frente C: servidor
  Etapas 1–4 con apps de prueba        Código de medición probado     Simulador, MQTT, base de
  (sin red eléctrica)                  con señales grabadas           datos y Grafana
        │                                    │                              │
        └──────────── Integración 1: firmware completo en la placa ─────────┤
                      (banco, sin red eléctrica)                            │
                                     └──── Integración 2: nodo real ─► servidor
                                                      │
                                     Etapa 5: revisión de seguridad firmada
                                                      │
                                     Etapa 6: sesión supervisada con red
```

### Frente A: hardware en el protoboard (persona A)

| Paso | Qué se hace | Programa que se usa | Prueba de salida |
|---|---|---|---|
| A1 | Etapa 1: placa sola | App de prueba de la etapa 1 (T027) | La placa arranca, se une al Wi-Fi y el LED RGB cambia de color |
| A2 | Etapa 2: pantalla, zumbador y LED | App de prueba de la etapa 2 (T028) | Texto en el OLED, pitido del zumbador, cada color del LED |
| A3 | Etapas 3 y 4: canales de tensión y corriente | Registrador del ADC (T029) | Vb ≈ 1,65 V con el adaptador desenchufado; *offset* del ACS712 ≈ 1,70 V sin corriente; onda alterna centrada en GPIO4 con el adaptador enchufado |
| A4 | Grabar señales reales | Registrador del ADC (T029), modo captura | Archivos de captura entregados al frente B |

Este frente **no** conecta nada a la red eléctrica: el ACS712 se prueba sin
corriente y el adaptador solo alimenta el canal de tensión.

### Frente B: firmware sin la placa (persona B)

El código de medición se escribe y se prueba con **señales grabadas o
sintéticas**, sin necesitar el protoboard armado: las pruebas corren en un
ESP32-S3 suelto conectado por USB (los cálculos puros también pueden probarse en
la computadora):

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

1. **Integración 1, firmware en la placa (banco, sin red eléctrica).** Requiere
   A3 y la prueba de salida de B. Se graba el *firmware* completo en el ESP32-S3
   del protoboard: la pantalla debe mostrar V cerca del valor esperado con el
   adaptador enchufado, corriente cercana a cero y el estado correcto del LED.
2. **Integración 2, nodo real con el servidor (T062).** Requiere la Integración 1
   y la prueba de salida de C. El nodo usa su propio certificado y sus datos
   deben aparecer en Grafana con la etiqueta «no validado». Se prueba también
   apagar el Wi-Fi unos minutos y comprobar que la cola se vacía al volver.
3. **Etapa 5, revisión de seguridad (T063).** La persona calificada arma o
   revisa la caja de ensayo y firma. Sin firma no hay paso 4.
4. **Etapa 6, sesión supervisada (T064).** Calibración nominal y prueba de
   plausibilidad con cargas reales (sección 10).

Si una integración falla, se vuelve al frente que corresponde (por ejemplo, un
valor raro de tensión vuelve al frente A o B) y se repite su prueba de salida
antes de integrar de nuevo. Nunca se depura con la red eléctrica conectada.

## 5. Etapa 1: ESP32-S3 por sí solo

Mantenga la placa desconectada de todos los sensores y de todo lo relacionado
con la red.

1. Instale o active el entorno ESP-IDF 5.4 LTS del proyecto.
2. Compile y grabe el *firmware* según las instrucciones del proyecto. Use solo
   la configuración de desarrollo y valores de ejemplo sin secretos donde se
   requiera configuración.
3. Alimente la placa con un cargador USB-C certificado. En etapas posteriores
   con red, no use un enlace USB a una computadora conectada a tierra salvo que
   la persona revisora lo apruebe.
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
2. Conecte SDA a GPIO8, SCL a GPIO9, VCC a 3V3 y GND a la tierra común.
3. El plan asume que el módulo tiene sus propias resistencias pull-up de I²C. No
   añada pull-ups no previstas sin revisar el módulo y el esquema.
4. Ejecute la prueba de pantalla y muestre una pantalla de estado simple con
   unidades o un texto de prueba. Verifique que se actualiza repetidamente.

**Aprobado si:** se detecta la pantalla I²C esperada y muestra texto estable y
legible.

### Zumbador activo: GPIO16 mediante 2N2222

1. No excite el zumbador de 5 V directamente desde un GPIO del ESP32.
2. Conecte GPIO16 a la base del 2N2222 a través de una resistencia de 1 kΩ.
   Conecte el emisor a la tierra común y el zumbador entre 5 V y el colector,
   como en el esquema de baja tensión revisado.
3. Confirme el orden de pines real del transistor en su hoja de datos antes de
   cablear; no es igual en todos los encapsulados.
4. Active brevemente el zumbador desde el *firmware* y confirme que lo conmuta el
   transistor. Apague antes de recablear.

**Aprobado si:** el zumbador suena cuando se le ordena, permanece apagado en otro
caso y el GPIO solo está conectado a través de la resistencia de base.

### LED RGB: GPIO17 / GPIO18 / GPIO21

1. Confirme que el LED es de cátodo común (asumido). Conecte el cátodo común a
   GND.
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
conductor de carga ni de red por el ACS712 en esta etapa.

### Circuito nominal

- Enchufe el conector del adaptador en el jack DC hembra con bornera y lleve
  dos cables jumper desde sus tornillos al protoboard; no se corta ningún cable.
  Mantenga el adaptador desenchufado de su tomacorriente protegido mientras
  cablea.
- Arme el nodo de polarización de 1,65 V (Vb): dos resistencias iguales de
  10 kΩ en serie entre 3V3 y GND, con 10 µF de Vb a GND.
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
3. Enchufe el adaptador certificado en un tomacorriente protegido solo después
   de revisar el cableado de baja tensión. Capture la forma de onda en GPIO4 y
   confirme una oscilación alterna centrada.
4. Para un adaptador de 9–15 V CA en vacío, el plan estima unos ±1,1 V de pico en
   GPIO4 en el caso de 15 V (unos 18 V RMS en vacío). Tómelo solo como una
   oscilación esperada aproximada; verifique en el banco el adaptador real y la
   forma de onda del ADC.
5. Confirme que la forma de onda permanece en el rango lineal del ADC y no se
   recorta. Si se recorta, deténgase y cambie el divisor solo mediante un cambio
   documentado y revisado del esquema. No improvise valores.

**Aprobado si:** Vb está cerca de 1,65 V con el adaptador desenchufado, el
adaptador produce en GPIO4 una forma de onda periódica centrada y no se observan
recortes ni tensiones inseguras. Anote la identidad del adaptador, su salida, la
forma de onda y la polarización medida.

## 8. Etapa 4: canal de corriente sin red eléctrica

Esta etapa verifica solo la salida de baja tensión del ACS712, sin corriente.
Ningún conductor pasa por IP+/IP−. La polaridad se comprueba después, en la
primera medición supervisada (etapa 6).

### Circuito nominal y verificaciones

1. Alimente el módulo ACS712 con 5 V del cargador USB-C certificado. El módulo
   tiene su propio condensador de desacoplo. Conecte su tierra de baja tensión a
   la tierra común.
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
rango del ADC. Esta etapa no usa la red eléctrica.

## 9. Etapa 5: caja de ensayo y revisión de seguridad por una persona calificada

No avance a ninguna conexión con la red hasta que el esquema completo y el
montaje físico se hayan inspeccionado desenergizados y la persona revisora haya
firmado abajo.

La persona revisora verifica y registra como mínimo:

- Identidad y versión del ACS712, construcción de los terminales del módulo,
  distancias de fuga y de aislamiento en aire, capacidad del conductor,
  polaridad y aptitud para el camino propuesto.
- Que el ACS712 es el único componente con red y está solo dentro de la caja
  de ensayo cerrada, que impide el contacto y es retardante de llama.
- Que solo el conector de baja tensión del ACS712 sale de esa caja y
  que los terminales de red están cubiertos e inaccesibles en uso normal.
- Que la entrada de cables, la sección de los conductores, las terminaciones,
  la sujeción, el soporte mecánico, las distancias y la integridad de la
  caja de ensayo son adecuados para el montaje revisado.
- Que el adaptador CA-CA tiene aislamiento certificado y es apto, incluida la
  conexión de sus cables de salida al divisor de tensión.
- Que el tomacorriente de prueba está protegido por un interruptor diferencial
  de 30 mA (del tablero del edificio o portátil certificado) que dispara con su
  botón de prueba, y que la llave termomagnética existente del circuito es
  aceptable para el cable de prueba, los terminales y el ACS712.
- Que el nodo se alimenta con el cargador USB-C certificado de baja tensión.
- Que no hay cableado de red en protoboards, cables jumper sueltos ni cables
  expuestos.
- El montaje controlado de prueba, la conexión de la carga, las condiciones de
  puesta a tierra y aislamiento, la polaridad, las verificaciones de tierra de
  protección cuando correspondan y la categoría del medidor.
- La política de USB: sin enlace a una computadora conectada a tierra mientras
  el prototipo esté energizado, salvo que la persona revisora apruebe ese
  arreglo concreto.
- Que las verificaciones desenergizadas visuales, de protección, polaridad,
  caja de ensayo, sujeción y conductores pueden completarse antes de la puesta en
  tensión supervisada.
- Que todos los supuestos pendientes y las capacidades de los componentes están
  resueltos o registrados explícitamente con una decisión segura.

### Registro de aprobación requerido

| Campo | Valor |
|---|---|
| Revisión del esquema / cableado | Por completar |
| Identificación de la caja de ensayo y las protecciones | Por completar |
| Versión del ACS712 y notas de revisión | Por completar |
| Nombre y calificación de la persona revisora | Por completar |
| Fecha de la revisión | Por completar |
| Condiciones / temas pendientes | Por completar |
| Firma de la persona revisora | Obligatoria antes de cualquier conexión a la red |
| Operador del montaje | Por completar |
| Autorización del montaje de prueba supervisado | La registra la persona revisora |

Una revisión sin firma, incompleta o condicionada no autoriza la conexión a la
red. Resuelva cada condición con la persona revisora primero.

## 10. Etapa 6: conexión supervisada y calibración

Esta etapa se realiza solo cuando la etapa 5 está completa y firmada. La persona
calificada supervisa el montaje controlado. No abra la caja de ensayo, no toque el
cableado ni haga ajustes con el circuito energizado. Si hace falta un cambio,
desenergice y deje que la persona calificada verifique la condición segura
antes de trabajar.

### Montaje de ensayo

```
Tomacorriente 220 V (diferencial 30 mA)
  ├─► Adaptador CA-CA ─► jack ─► protoboard ─► GPIO4   (tensión de la carga)
  └─► Caja de ensayo: enchufe ─► ACS712 (fase) ─► tomacorriente ─► carga
                                   └─► 5 V, GND, OUT ─► protoboard ─► GPIO5
ESP32-S3 (cargador USB-C) ─► Wi-Fi ─► servidor ─► panel
```

No se usa multímetro de referencia: el prototipo funciona con coeficientes
nominales y sus lecturas se rotulan como «no validadas» (constitución 2.0.0).

1. Registre la revisión del montaje, el *commit* del *firmware*, la
   configuración del ADC, el adaptador de tensión, el modelo y versión del
   ACS712, el cableado, el operador, las condiciones ambientales, la
   identidad y la potencia de placa de cada carga, y que no se usó instrumento
   de referencia.
2. Pulse el botón de prueba del interruptor diferencial de 30 mA y confirme que
   dispara; rearme. Confirme que se usan la caja de ensayo cerrada y revisada y las
   conexiones de prueba controladas.
3. Cargue los coeficientes nominales: ganancia de tensión según la relación del
   adaptador y R1/R2, ganancia de corriente según 100 mV/A y R3/R4, y corrección
   de fase según el desfase conocido de una conversión entre canales.
4. Caliente el sistema al menos 10 minutos. Sin carga, capture 60 segundos de
   datos de corriente cero y guarde el *offset* del ACS712. Repita el autocero
   antes de cada sesión.
5. Encienda una carga resistiva estable. La potencia debe salir positiva: eso
   confirma la polaridad del ACS712. Si sale negativa, corrija el signo en los
   coeficientes; no recablee. Guarde el resultado como revisión de calibración
   `nominal` y congélela.
6. Prueba de plausibilidad con al menos tres cargas resistivas estables (unos
   100 W, 500 W y 1 kW): la tensión debe estar entre 180 y 250 V, la potencia
   debe ser positiva y quedar dentro de ±15 % de la potencia de placa. Registre
   al menos 5 minutos por carga.
7. Registre un ventilador pequeño solo para observar su comportamiento de V, I y
   P, sin criterio numérico.
8. Sin carga o por debajo del rango, la corriente usa un límite absoluto de
   ruido, no un porcentaje.
9. Conserve extractos de la forma de onda cruda, resúmenes, *scripts*, entorno,
   coeficientes, revisiones de *firmware* y cableado, *hashes* y la tabla de
   plausibilidad. Marque los datos fuera de rango.

La prueba de plausibilidad describe solo la configuración probada del prototipo
educativo; no es una afirmación de exactitud. No aprueba una instalación permanente, la
facturación ni el uso como dispositivo de seguridad.

## 11. Solución de problemas

| Síntoma | Causa probable | Verificación |
|---|---|---|
| El ESP32-S3 no arranca | Destino o compilación incorrectos, alimentación o grabación | Revise la identidad de la placa, el cargador y cable USB-C, la salida de compilación y el registro de arranque |
| El Wi-Fi no se conecta | Credenciales locales o configuración de la red Wi-Fi local | Verifique el aprovisionamiento localmente; nunca copie secretos en registros ni en esta guía |
| El OLED no muestra nada | Módulo SPI, SDA/SCL invertidos, alimentación o dirección/configuración | Confirme el supuesto de I²C de 4 pines; revise GPIO8/9, 3V3, GND y la configuración del *firmware* |
| El zumbador no suena o no se apaga | Orden de pines del transistor, resistencia de base o cableado | Apague; verifique el orden de pines del 2N2222, GPIO16–1 kΩ–base, emisor a GND y el camino zumbador/colector |
| Falta un color del RGB | Tipo de LED u orden de pines, o falta la resistencia en serie | Confirme el supuesto de cátodo común y el mapa GPIO17/18/21; verifique cada resistencia de 470 Ω |
| Vb no está cerca de 1,65 V | Error en el divisor de polarización, la tierra o el condensador de 10 µF | Con el adaptador desenchufado, mida Vb y revise el divisor de dos 10 kΩ |
| La señal en GPIO4 se recorta | El divisor o la salida del adaptador difieren del valor nominal | Deténgase; anote la forma de onda y el adaptador; cambie solo mediante revisión del esquema |
| No hay oscilación en GPIO4 | Adaptador desenchufado, jumper suelto en la bornera o el protoboard, o error en R1/R2/Vb | Confirme que el adaptador es de salida CA, ajuste los tornillos del jack, reinserte los jumpers y revise el esquema de baja tensión |
| El *offset* en GPIO5 está lejos de ~1,70 V | Alimentación del ACS712, divisor, tierra o versión del sensor | Verifique 5 V, tierra común, R3 = 4,7 kΩ, R4 = 10 kΩ y que el módulo sea el de 20 A |
| La potencia activa sale negativa | Sentido del conductor en IP+/IP− | Si la potencia sale negativa en la carga resistiva, corrija el signo en los coeficientes de calibración; no recablee con tensión |
| Los valores del ADC saltan o se pierden muestras | Ruido de cableado, configuración del ADC, desbordamiento de DMA o conversión faltante | Revise tierras y filtros de baja tensión y el diagnóstico del *firmware*; las ventanas afectadas son inválidas |
| La calibración deriva | Calentamiento, variación de la alimentación, temperatura, carga inestable o coeficientes nominales | Repita el calentamiento y el cero registrados y use cargas estables y el multímetro identificado |
| La persona revisora encuentra un tema de seguridad pendiente | Capacidad, caja de ensayo, protección o cableado no establecidos | Deténgase; resuélvalo y obtenga la firma antes de cualquier conexión a la red |

## 12. Temas pendientes y supuestos

- Se asume que el OLED es un módulo SSD1306 I²C de 4 pines. Confirme el módulo
  real; una pantalla SPI de 7 pines cambia la asignación de pines y requiere una
  actualización revisada.
- Se asume que el LED RGB es de cátodo común. Confirme su tipo y orden de pines
  antes de conectar GPIO17/18/21.
- No hay multímetro de referencia (constitución 2.0.0). Si más adelante el
  equipo consigue uno True RMS (por ejemplo, prestado por la persona revisora),
  puede añadirse una calibración `reference` sin cambiar el circuito.
- El adaptador CA-CA certificado está por comprar. Verifique en el banco su
  certificación, su salida y su aptitud antes de usarlo.
- El circuito de baja tensión va en protoboard, fuera de la caja de ensayo del
  ACS712; su ubicación junto a la caja está por revisar. Conserve los valores de divisores,
  polarización y filtros del plan; no sustituya valores no listados.
- Protección diferencial: revisar si el tablero eléctrico del edificio tiene un
  interruptor diferencial de 30 mA (botón "T") que proteja el tomacorriente de
  prueba; si no, comprar un protector diferencial portátil certificado. Sin
  diferencial no se conecta nada a la red.
- Persona calificada: identificar al electricista o docente que hará la
  revisión y firmará el registro de la etapa 5.
- Los pines propuestos del ADC, la atenuación y configuración del ADC y los
  parámetros exactos de calibración del *firmware* se confirman en la revisión
  del esquema y en el banco.
- La identidad de la persona revisora, el registro de seguridad firmado, la
  identidad de las cargas, la calibración nominal y la tabla de plausibilidad
  deben completarse antes de mostrar cualquier medición, siempre rotulada como
  «no validada».
