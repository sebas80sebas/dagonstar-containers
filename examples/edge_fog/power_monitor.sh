#!/bin/bash
SECONDS=50

BOTH=$(mktemp)
CURRENT=$(mktemp)
TENSION=$(mktemp)
CONSUMPTION=$(mktemp)

echo "Monitoreo iniciado durante $SECONDS segundos..."
echo ""

for i in $(seq 1 $SECONDS); do
    sleep 1

    if ! vcgencmd pmic_read_adc > "$BOTH" 2>/dev/null; then
        echo "Warning: fallo pmic_read_adc en sample $i/$SECONDS"
        continue
    fi

    grep current "$BOTH" | awk '{print $2}' | sed 's/.*=//;s/mA//;s/mV//' > "$CURRENT"
    grep volt "$BOTH"    | awk '{print $2}' | sed 's/.*=//;s/mA//;s/mV//' | head -12 > "$TENSION"

    if [ ! -s "$CURRENT" ] || [ ! -s "$TENSION" ]; then
        echo "Warning: muestra $i sin datos válidos"
        rm -f "$CURRENT" "$TENSION" "$BOTH"
        continue
    fi

    paste "$CURRENT" "$TENSION" | awk '{sum+=$1*$2} END {print sum}' >> "$CONSUMPTION"

    rm -f "$CURRENT" "$TENSION" "$BOTH"
done

echo ""
echo "Cálculo final..."
echo ""

awk '{sumX+=$1; sumX2+=($1*$1)} END {
    if (NR>1) {
        printf "Average_power_consumption= %.3f +/- %.3f W\n", sumX/NR*1.1451+0.5879, sqrt((sumX2-(sumX*sumX)/NR)/(NR-1)/NR)*1.1451
    } else {
        print "ERROR: No hay suficientes muestras"
    }
}' "$CONSUMPTION"

rm -f "$CONSUMPTION"

