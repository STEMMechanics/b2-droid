"""Arduino 8x8 display transport with dynamic frame support."""


class DisplayService:
    def __init__(self, write_line):
        self.write_line = write_line

    def show(self, rows):
        if len(rows) != 8:
            raise ValueError("an 8x8 frame requires exactly eight rows")
        values = []
        for row in rows:
            if isinstance(row, str):
                if len(row) != 8 or any(bit not in "01" for bit in row):
                    raise ValueError("string rows must contain eight binary digits")
                row = int(row, 2)
            value = int(row)
            if not 0 <= value <= 255:
                raise ValueError("matrix rows must be between 0 and 255")
            values.append(value)
        payload = "".join(f"{value:02x}" for value in values)
        self.write_line(f"matrix:{payload}")
        return payload

    def context(self):
        return {
            "display": "8x8 monochrome LED matrix",
            "dynamic_frames": True,
            "format": "eight rows of eight bits",
        }
