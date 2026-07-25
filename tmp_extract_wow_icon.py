# Wow.exe 리소스에서 256px 아이콘을 알파 보존 추출 → app/static/wow.ico (멀티사이즈)
# pywin32 없이 순수 ctypes(GDI): PrivateExtractIconsW → GetIconInfo → GetDIBits(32bpp)
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PIL import Image

EXE = r"C:\Program Files (x86)\World of Warcraft\_retail_\Wow.exe"
OUT = Path(__file__).parent / "app" / "static" / "wow.ico"

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
SIZE = 256


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


hicons = (ctypes.c_void_p * 1)()
ids = (ctypes.c_uint * 1)()
n = user32.PrivateExtractIconsW(EXE, 0, SIZE, SIZE, hicons, ids, 1, 0)
if n < 1 or not hicons[0]:
    print("추출 실패"); sys.exit(1)
hicon = hicons[0]

ii = ICONINFO()
if not user32.GetIconInfo(ctypes.c_void_p(hicon), ctypes.byref(ii)):
    print("GetIconInfo 실패"); sys.exit(1)

bih = BITMAPINFOHEADER()
bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
bih.biWidth = SIZE
bih.biHeight = -SIZE          # top-down
bih.biPlanes = 1
bih.biBitCount = 32
bih.biCompression = 0         # BI_RGB
buf = ctypes.create_string_buffer(SIZE * SIZE * 4)
hdc = user32.GetDC(0)
got = gdi32.GetDIBits(ctypes.c_void_p(hdc), ctypes.c_void_p(ii.hbmColor),
                      0, SIZE, buf, ctypes.byref(bih), 0)
user32.ReleaseDC(0, ctypes.c_void_p(hdc))
gdi32.DeleteObject(ctypes.c_void_p(ii.hbmColor))
gdi32.DeleteObject(ctypes.c_void_p(ii.hbmMask))
user32.DestroyIcon(ctypes.c_void_p(hicon))
if got != SIZE:
    print(f"GetDIBits {got}행 — 실패"); sys.exit(1)

img = Image.frombuffer("RGBA", (SIZE, SIZE), buf.raw, "raw", "BGRA", 0, 1)
if img.getextrema()[3] == (0, 0):   # 알파 전부 0 = 마스크 미반영 아이콘 — 불투명 처리
    img.putalpha(255)
img.save(OUT, format="ICO",
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(f"OK {SIZE}px → {OUT} ({OUT.stat().st_size} bytes)")
