#!/usr/bin/env python3
"""Quick test of Kestrel 5500L driver. Toggle BLE on the device before running."""

import asyncio
from rf_bench.kestrel import Kestrel5500

MAC = "88:6B:0F:5F:D0:EB"
KNOWN_ALTITUDE_M = 2003.0  # known true altitude for QNH computation


async def main():
    print(f"Connecting to Kestrel at {MAC}...")
    print("(Toggle Bluetooth on the Kestrel if it's not advertising)")
    print()

    async with Kestrel5500(MAC) as kestrel:
        info = await kestrel.get_device_info()
        print(f"Model:    {info.model}")
        print(f"Serial:   {info.serial}")
        print(f"Firmware: {info.firmware}")
        print(f"Hardware: {info.hardware}")
        print(f"Battery:  {info.battery_percent}%")
        print()
        print("Streaming live data (Ctrl-C to stop):")
        print("=" * 60)

        count = 0
        async for reading in kestrel.stream():
            if reading.temperature_c is None:
                continue
            print(f"  Temperature:     {reading.temperature_f:.1f}°F  ({reading.temperature_c:.2f}°C)")
            print(f"  Humidity:        {reading.relative_humidity:.1f}%")
            print(f"  Wind:            {reading.wind_speed_mph:.1f} mph  ({reading.wind_speed_ms:.2f} m/s)")
            print(f"  Station press:   {reading.station_pressure_inhg:.2f} inHg  ({reading.station_pressure_mbar:.1f} mbar)")
            if reading.altitude_ft is not None:
                print(f"  Pressure alt:    {reading.altitude_ft:.0f} ft  ({reading.altitude_m:.1f} m)")
            if reading.dew_point_c is not None:
                print(f"  Dew point:       {reading.dew_point_f:.1f}°F")
            if reading.wet_bulb_c is not None:
                print(f"  Wet bulb:        {reading.wet_bulb_f:.1f}°F")
            if reading.heat_index_c is not None:
                print(f"  Heat index:      {reading.heat_index_f:.1f}°F")

            # Derived values
            print(f"  --- Derived ---")
            if reading.vapor_pressure_mbar is not None:
                print(f"  Vapor pressure:  {reading.vapor_pressure_mbar:.2f} mbar")
            if reading.air_density is not None:
                print(f"  Air density:     {reading.air_density:.4f} kg/m³")
            if reading.density_altitude_ft is not None:
                print(f"  Density alt:     {reading.density_altitude_ft:.0f} ft")
            if reading.speed_of_sound_ms is not None:
                print(f"  Speed of sound:  {reading.speed_of_sound_ms:.1f} m/s")
            if reading.rf_refractivity is not None:
                print(f"  RF refractivity: {reading.rf_refractivity:.1f} N")
            if reading.cloud_base_agl_ft is not None:
                print(f"  Cloud base AGL:  {reading.cloud_base_agl_ft:.0f} ft")
            wc = reading.wind_chill_f
            if wc is not None:
                print(f"  Wind chill:      {wc:.1f}°F")

            # QNH from known altitude
            qnh = reading.sea_level_pressure_inhg(KNOWN_ALTITUDE_M)
            if qnh is not None:
                print(f"  QNH (from {KNOWN_ALTITUDE_M:.0f}m): {qnh:.2f} inHg")

            print("=" * 60)

            count += 1
            if count >= 5:
                break

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
