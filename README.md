# Solplanet EMS

Sistema de gestión energética (EMS) para inversores Solplanet con batería. Publica datos en tiempo real vía MQTT para integración con Home Assistant y almacena histórico en MySQL/MariaDB.

Energy Management System for Solplanet inverters with battery storage. Publishes real-time data via MQTT for Home Assistant integration and stores history in MySQL/MariaDB.

---

## Características / Features

- 🔌 Lectura directa del inversor Solplanet vía HTTP (API local)
- 🔋 Monitorización completa: solar, batería, red, consumo
- 📡 Publicación MQTT compatible con Home Assistant (auto-discovery ready)
- 💾 Almacenamiento en MySQL/MariaDB (live + histórico + diario)
- ⚡ Control remoto vía MQTT: cambio de modo, SOC, schedule
- 🐳 Despliegue con Docker

---

## Arquitectura / Architecture

```
┌──────────────┐     HTTP      ┌──────────────────┐     MQTT      ┌─────────────────┐
│   Solplanet  │◄─────────────►│  solplanet-ems   │──────────────►│ Home Assistant   │
│   Inverter   │               │                  │               │ (MQTT broker)    │
└──────────────┘               │  - polling 10s   │               └─────────────────┘
                               │  - EMS logic     │
                               │  - commands      │     SQL
                               │                  │──────────────►┌─────────────────┐
                               └──────────────────┘               │ MySQL/MariaDB   │
                                                                  └─────────────────┘
```

---

## Requisitos / Requirements

- Python 3.11+
- Inversor Solplanet con API HTTP local (puerto 8484)
- MQTT broker (Mosquitto recomendado)
- MySQL o MariaDB (opcional, para histórico)
- Docker (recomendado)

---

## Instalación / Installation

### Con Docker (recomendado)

```bash
git clone https://github.com/python8708/solplanet-ems.git
cd solplanet-ems
cp .env.example .env
# Edita .env con tus datos
docker compose up -d
```

### Sin Docker

```bash
git clone https://github.com/python8708/solplanet-ems.git
cd solplanet-ems
pip install -r requirements.txt
cp .env.example .env
# Edita .env con tus datos
python main.py
```

### Base de datos

Las tablas se crean automáticamente al arrancar. Si prefieres crearlas manualmente:

```bash
mysql -u root -p < schema.sql
```

---

## Configuración / Configuration

Copia `.env.example` a `.env` y configura:

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `INVERTER_URL` | URL del inversor | `http://192.168.x.x:8484` |
| `BATTERY_SN` | Nº serie batería (auto-detectado si vacío) | `PBxxxxx` |
| `MQTT_HOST` | Host del broker MQTT | `localhost` |
| `MQTT_USER` | Usuario MQTT | `mqtt_user` |
| `MQTT_PASSWORD` | Contraseña MQTT | `secret` |
| `DB_HOST` | Host MySQL | `localhost` |
| `DB_USER` | Usuario MySQL | `ems_user` |
| `DB_PASSWORD` | Contraseña MySQL | `secret` |
| `POLL_INTERVAL` | Segundos entre lecturas | `10` |

Ver `.env.example` para la lista completa.

---

## Comandos MQTT / MQTT Commands

Publica JSON en el topic `solplanet/comando`:

```json
// Cambiar modo batería
{"mode": 2}

// Ajustar límites SOC
{"charge_max": 100, "discharge_max": 10}

// Programar schedule
{"action": "set_schedule", "day": "lunes", "slots": [...]}
```

Modos de batería:
- `2` - Auto (por defecto)
- `3` - Carga forzada
- `4` - Descarga forzada
- `5` - Backup

---

## Topics MQTT

| Topic | Dirección | Contenido |
|-------|-----------|-----------|
| `solplanet/estado` | → HA | Estado completo JSON |
| `solplanet/comando` | ← HA | Comandos de control |
| `solplanet/debug` | → HA | Info debug |
| `solplanet/disponibilidad` | → HA | online/offline |
| `solplanet/energia` | → HA | Estadísticas energéticas |

---

## Estructura del proyecto / Project Structure

```
solplanet-ems/
├── main.py              # Bucle principal
├── config.py            # Configuración desde .env
├── solplanet_client.py  # Cliente HTTP del inversor
├── mqtt_client.py       # Cliente MQTT + auto-discovery
├── database.py          # Persistencia MySQL
├── models.py            # Modelos de datos
├── commands.py          # Procesador de comandos MQTT
├── calculations.py      # Cálculos energéticos
├── energy_stats.py      # Estadísticas diarias
├── logger.py            # Logging configurado
├── requirements.txt     # Dependencias Python
├── Dockerfile           # Imagen Docker
├── docker-compose.yml   # Despliegue
├── schema.sql           # Schema de base de datos
├── .env.example         # Plantilla de configuración
└── .gitignore
```

---

## Inversores compatibles / Compatible Inverters

Probado con inversores Solplanet que exponen API HTTP en el puerto 8484. Modelos conocidos:

- ASW 3-6K-LT-G2 (híbridos con batería)

Si funciona con tu modelo, abre un issue para añadirlo a la lista.

---

## Licencia / License

MIT

---

## Contribuir / Contributing

1. Fork del repositorio
2. Crea tu rama (`git checkout -b feature/nueva-funcionalidad`)
3. Commit (`git commit -m 'Añade nueva funcionalidad'`)
4. Push (`git push origin feature/nueva-funcionalidad`)
5. Abre un Pull Request
