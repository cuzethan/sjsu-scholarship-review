import pandas as pd

path = r"C:\Users\sfkim\OneDrive\Desktop\dxHub\recsuaisummercampdatarequestandphoneanexpert\SJSU General Scholarships 26-27 scores.xlsx"
xl = pd.ExcelFile(path)
print(f"Sheets: {xl.sheet_names}\n")

for sheet in xl.sheet_names:
    df = pd.read_excel(path, sheet_name=sheet, nrows=5)
    print(f"Sheet: '{sheet}' | Rows: {len(pd.read_excel(path, sheet_name=sheet))} | Columns: {len(df.columns)}")
    print(f"Columns:")
    for i, col in enumerate(df.columns):
        print(f"  [{i}] {col}")
    print(f"\nFirst 3 rows:")
    print(df.head(3).to_string())
    print("\n" + "="*80 + "\n")
