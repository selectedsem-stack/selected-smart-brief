import base64
import io
import qrcode


def qr_data_uri(url: str) -> str:
    """Return a data:image/png;base64 URI for a QR code of the given URL."""
    img = qrcode.make(url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
