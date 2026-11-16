#!/bin/bash
set -e

echo "====================================================="
echo " Installing FUXA Industrial Communication Drivers"
echo " (OPC UA, Modbus RTU/TCP, Siemens S7)"
echo "====================================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(dirname "$SCRIPT_DIR")/server"

cd "$SERVER_DIR"

echo "[1/3] Installing node-opcua and modbus-serial into server/node_modules..."
npm install node-opcua@^2.149.0 modbus-serial@^8.0.19 --no-audit --no-fund --save

echo "[2/3] Verifying driver modules..."
node -e "
try { require('node-opcua'); console.log('  ✓ node-opcua loaded successfully'); } catch(e) { console.error('  ✗ node-opcua load failed:', e.message); }
try { require('modbus-serial'); console.log('  ✓ modbus-serial loaded successfully'); } catch(e) { console.error('  ✗ modbus-serial load failed:', e.message); }
try { require('nodes7'); console.log('  ✓ nodes7 loaded successfully'); } catch(e) { console.error('  ✗ nodes7 load failed:', e.message); }
"

echo "[3/3] Reloading FUXA in PM2..."
if command -v pm2 &> /dev/null; then
    pm2 restart P9_FUXA_Enterprise --update-env 2>/dev/null || pm2 restart all --update-env 2>/dev/null || true
    echo "[✓] PM2 process reloaded."
else
    echo "[!] PM2 not found on PATH. Please restart FUXA manually."
fi

echo "====================================================="
echo " Driver installation completed successfully!"
echo " Open FUXA -> Devices -> Add Device (+):"
echo " OPCUA, ModbusRTU, ModbusTCP, SiemensS7 are now available."
echo "====================================================="
