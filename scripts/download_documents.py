"""
Script to download official HDFC Mutual Fund documents into data/raw/.
"""

import os
import sys
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

DOCUMENTS = [
    # SIDs
    {
        "filename": "HDFC_Nifty_50_Index_Fund_SID.pdf",
        "url": "https://files.hdfcfund.com/s3fs-public/SID/2025-11/SID%20-%20HDFC%20Nifty%2050%20Index%20Fund%20dated%20November%2021%2C%202025.pdf?VersionId=Jmmq_EBa5XtCNwbTco3cO4SzNxWTro4U",
        "title": "HDFC Nifty 50 Index Fund - Scheme Information Document (SID)",
        "scheme": "HDFC Nifty 50 Index Fund",
        "type": "SID"
    },
    {
        "filename": "HDFC_Flexi_Cap_Fund_SID.pdf",
        "url": "https://files.hdfcfund.com/s3fs-public/SID/2025-11/SID%20-%20HDFC%20Flexi%20Cap%20Fund%20dated%20November%2021%2C%202025_0.pdf?VersionId=8eR7i2.EGl_5.cJAlLh6vNEfqjEE0vb2",
        "title": "HDFC Flexi Cap Fund - Scheme Information Document (SID)",
        "scheme": "HDFC Flexi Cap Fund",
        "type": "SID"
    },
    {
        "filename": "HDFC_ELSS_Tax_Saver_Fund_SID.pdf",
        "url": "https://files.hdfcfund.com/s3fs-public/SID/2025-11/SID%20-%20HDFC%20ELSS%20Tax%20Saver%20dated%20November%2021%2C%202025.pdf?VersionId=DungYvv2dhOQ1qZfNi4xvypECzXU_tEu",
        "title": "HDFC ELSS Tax Saver Fund - Scheme Information Document (SID)",
        "scheme": "HDFC ELSS Tax Saver Fund",
        "type": "SID"
    },
    # KIMs
    {
        "filename": "HDFC_Nifty_50_Index_Fund_KIM.pdf",
        "url": "https://files.hdfcfund.com/s3fs-public/KIM/2025-11/KIM%20-%20HDFC%20Nifty%2050%20Index%20Fund%20dated%20November%2021%2C%202025.pdf?VersionId=XoN7EsnKZhJe5ZyUI0Ki.eMgf5nBNakM",
        "title": "HDFC Nifty 50 Index Fund - Key Information Memorandum (KIM)",
        "scheme": "HDFC Nifty 50 Index Fund",
        "type": "KIM"
    },
    {
        "filename": "HDFC_Flexi_Cap_Fund_KIM.pdf",
        "url": "https://files.hdfcfund.com/s3fs-public/KIM/2025-11/KIM%20-%20HDFC%20Flexi%20Cap%20Fund%20dated%20November%2021%2C%202025_1.pdf?VersionId=kjfKm83nM5q0LDh1xu645ZXrnetxOtVr",
        "title": "HDFC Flexi Cap Fund - Key Information Memorandum (KIM)",
        "scheme": "HDFC Flexi Cap Fund",
        "type": "KIM"
    },
    {
        "filename": "HDFC_ELSS_Tax_Saver_Fund_KIM.pdf",
        "url": "https://files.hdfcfund.com/s3fs-public/KIM/2025-11/KIM%20-%20HDFC%20ELSS%20Tax%20Saver%20dated%20November%2021%2C%202025_0.pdf?VersionId=CWvBjiK_hIuApMLzaZJVRt17Sc6tmlog",
        "title": "HDFC ELSS Tax Saver Fund - Key Information Memorandum (KIM)",
        "scheme": "HDFC ELSS Tax Saver Fund",
        "type": "KIM"
    },
    # Services & Forms
    {
        "filename": "HDFC_Common_Transaction_Form_Non_Financial.pdf",
        "url": "https://files.hdfcfund.com/s3fs-public/2026-11/Common%20Transaction%20Form%20-%20Non%20Financial%20Transactions%20051126%20Editable.pdf?VersionId=tYGA6ImI8ITPROUc8GLqUQcfJbbNHMDD",
        "title": "HDFC Common Transaction Form - Non-Financial Requests & Account Services",
        "scheme": "General Account Operations",
        "type": "Service_Form"
    }
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

def download_file(item):
    filepath = RAW_DIR / item["filename"]
    print(f"Downloading [{item['type']}] {item['title']}...")
    try:
        req = urllib.request.Request(item["url"], headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response, open(filepath, 'wb') as out_file:
            data = response.read()
            out_file.write(data)
        size_kb = round(filepath.stat().st_size / 1024, 2)
        print(f"  -> Saved {item['filename']} ({size_kb} KB)")
        return True
    except Exception as e:
        print(f"  -> ERROR downloading {item['filename']}: {e}")
        return False

if __name__ == "__main__":
    success_count = 0
    for doc in DOCUMENTS:
        if download_file(doc):
            success_count += 1
    print(f"\nDownload completed: {success_count}/{len(DOCUMENTS)} files downloaded successfully.")
