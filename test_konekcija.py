"""
test_konekcija.py

Samostalni test-skript za provjeru da firebird-driver ispravno radi na vasem
racunalu prije nego krenemo dalje s aplikacijom. Pokrenite ga s:

    python test_konekcija.py

Ako sve prode kako treba, ispisat ce verziju Firebird servera i popis
generatora u bazi. Ako fbclient.dll nije pronaden, dobit cete jasnu gresku -
u tom slucaju otkomentirajte i ispravite FB_CLIENT_LIBRARY putanju ispod.
"""

# Ako firebird-driver ne moze sam pronaci fbclient.dll (nije u PATH-u),
# otkomentirajte sljedece dvije linije i upisite tocnu putanju:
#
# from firebird.driver import driver_config
# driver_config.fb_client_library.value = r"C:\Program Files\Firebird\Firebird_3_0\fbclient.dll"

from firebird.driver import connect

# --- PRILAGODITE OVO VASIM STVARNIM PODACIMA ---
DATABASE = r"localhost/3050:D:\iSustavMW\Podaci\MICROWORLD-2026IS.FDB"
USER = "SYSDBA"
PASSWORD = "masterkey"
# ------------------------------------------------

print(f"Pokusavam se spojiti na: {DATABASE}")

try:
    con = connect(DATABASE, user=USER, password=PASSWORD)
except Exception as e:
    print(f"GRESKA PRI SPAJANJU: {type(e).__name__}: {e}")
    raise SystemExit(1)

print("Uspjesno spojeno!")
print("Firebird server verzija:", con.info.engine_version)

cur = con.cursor()
cur.execute("""
    SELECT RDB$GENERATOR_NAME
    FROM RDB$GENERATORS
    WHERE RDB$SYSTEM_FLAG = 0
    ORDER BY RDB$GENERATOR_NAME
""")
generators = [row[0].strip() for row in cur.fetchall()]

print(f"\nPronadeno {len(generators)} korisnickih generatora u bazi.")
print("Provjeravam postoje li nasi ocekivani generatori:")
for gen_name in ("GENIDTVRTKE", "GENIDVPRZG", "GENIDVPRST", "GENIDROBE"):
    status = "OK" if gen_name in generators else "NEDOSTAJE!"
    print(f"  {gen_name}: {status}")

con.close()
print("\nKonekcija zatvorena. Test gotov.")