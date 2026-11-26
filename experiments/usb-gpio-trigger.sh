#!/bin/bash
# /usr/local/bin/usb-gpio-trigger.sh
# Aufruf: usb-gpio-trigger.sh <on|off> <KERNELS-Port, z.B. 5-1>

ACTION="$1"
PORT="$2"
LOCKFILE="/tmp/usb-gpio-${PORT}.lock"

exec 200>"$LOCKFILE"
flock -n 200 || exit 1

# Mapping: Port-Pfad -> GPIO-Chip/Line
case "$PORT" in
  5-1)  GPIOCHIP="gpiochip4"; LINE="10" ;;   # "USB 1"
  2-1)  GPIOCHIP="gpiochip4"; LINE="11" ;;   # "USB 2"
  3-1)  GPIOCHIP="gpiochip4"; LINE="9"  ;;   # "USB 3"
  *)
    logger -t usb-gpio "Unbekannter Port: $PORT"
    exit 1
    ;;
esac

case "$ACTION" in
  on)
    gpioset --mode=exit "$GPIOCHIP" "${LINE}=1"
    logger -t usb-gpio "Port $PORT -> GPIO ${GPIOCHIP}:${LINE} = 1"
    ;;
  off)
    gpioset --mode=exit "$GPIOCHIP" "${LINE}=0"
    logger -t usb-gpio "Port $PORT -> GPIO ${GPIOCHIP}:${LINE} = 0"
    ;;
  *)
    echo "Usage: $0 {on|off} <port>" >&2
    exit 1
    ;;
esac
