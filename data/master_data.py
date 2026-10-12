"""All data below are synthetic demo assumptions, not specifications."""
import pandas as pd

PRODUCTS = [
 ("P-001","Menthol","P1 – Reinstoff fest","SOLID|GC_SUITABLE|KF_SUITABLE|MELTING_POINT|SENSORY"),
 ("P-002","Thymol","P1 – Reinstoff fest","SOLID|GC_SUITABLE|KF_SUITABLE|MELTING_POINT|SENSORY"),
 ("P-003","Benzoesäure","P1 – Reinstoff fest","SOLID|ACID|TITRATABLE|MELTING_POINT"),
 ("P-004","Ethanol","P2 – Reinstoff flüssig","LIQUID|GC_SUITABLE|NIR_SUITABLE|KF_SUITABLE|VOLATILE"),
 ("P-005","Triethylamin","P2 – Reinstoff flüssig","LIQUID|BASE|GC_SUITABLE|TITRATABLE|VOLATILE"),
 ("P-006","Lactase-Präparat","P3 – Enzymprodukt","ENZYME|LIQUID|PHOTOMETRIC|VISCOSIMETRIC"),
 ("P-007","Bromelain-Granulat","P3 – Enzymprodukt","ENZYME|GRANULATE|PHOTOMETRIC|VISCOSIMETRIC"),
 ("P-008","Linalool","P4 – Riechstoff","LIQUID|VOLATILE|GC_SUITABLE|SENSORY"),
 ("P-009","Vanillin","P4 – Riechstoff","SOLID|GC_SUITABLE|MELTING_POINT|SENSORY"),]
METHODS = [
 ("M-GC","GC-Reinheit","Reinheit","%","GC-01|GC-02"), ("M-KF","Karl-Fischer","Wasser","%","KF-01"),
 ("M-MP","Schmelzpunkt","Schmelzpunkt","°C","MP-01"), ("M-AT","Säure-/Base-Titration","Gehalt","%","TIT-01"),
 ("M-NIR","NIR-Analyse","Reinheit","%","NIR-01"), ("M-PHOTO","Photometrische Enzymaktivität","Aktivität","U/g","UVVIS-01"),
 ("M-VISKO","Viskosimetrische Enzymaktivität","Aktivität","U/g","VISKO-01"), ("M-SENS","Sensorik / Riechtest","Sensorik-Score","Score","MANUELL")]
INSTRUMENTS = [("GC-01","Gaschromatograph"),("GC-02","Gaschromatograph"),("NIR-01","NIR-Spektrometer"),
 ("KF-01","Karl-Fischer-Titrator"),("UVVIS-01","UV/VIS-Spektrometer"),("VISKO-01","Viskosimeter"),
 ("MP-01","Schmelzpunktgerät"),("TIT-01","Titrator")]
EMPLOYEES = [("E-01","Anna Becker","Laborant"),("E-02","Daniel Fischer","Laborant"),("E-03","Elena Hoffmann","Laborant"),
 ("E-04","Jonas König","Laborant"),("E-05","Mira Wagner","Laborant"),("E-06","Dr. Lea Roth","Laborleiter")]

# product -> (method, target, LSL, USL, sigma); deliberately synthetic
PLANS = {
 "P-001":[("M-GC",99.5,98.5,100.0,.35),("M-KF",0.10,0,0.30,.05),("M-MP",42.5,41.5,43.5,.25),("M-SENS",4.5,3.0,5.0,.4)],
 "P-002":[("M-GC",99.0,98.0,100.0,.45),("M-KF",0.10,0,0.30,.05),("M-MP",49.0,48.0,51.0,.35),("M-SENS",4.3,3.0,5.0,.4)],
 "P-003":[("M-AT",99.5,98.0,101.0,.45),("M-MP",122.0,120.0,124.0,.4)],
 "P-004":[("M-GC",99.7,99.0,100.0,.25),("M-NIR",99.7,99.0,100.0,.30),("M-KF",0.08,0,0.20,.035)],
 "P-005":[("M-GC",99.2,98.0,100.0,.5),("M-AT",99.0,97.5,101.0,.55)],
 "P-006":[("M-PHOTO",1000,850,1150,55),("M-VISKO",980,820,1140,65)],
 "P-007":[("M-PHOTO",1200,1020,1380,65),("M-VISKO",1180,1000,1360,75)],
 "P-008":[("M-GC",98.5,97.0,100.0,.55),("M-SENS",4.2,3.0,5.0,.4)],
 "P-009":[("M-GC",99.0,98.0,100.0,.45),("M-MP",82.0,80.0,84.0,.4),("M-SENS",4.4,3.0,5.0,.35)],}

def frames():
    return {"products":pd.DataFrame(PRODUCTS,columns=["product_id","product","product_class","tags"]),
      "methods":pd.DataFrame(METHODS,columns=["method_id","method","parameter","unit","eligible_instruments"]),
      "instruments":pd.DataFrame(INSTRUMENTS,columns=["instrument_id","instrument"]),
      "employees":pd.DataFrame(EMPLOYEES,columns=["employee_id","employee","role"])}
