from smartcard.System import readers
from smartcard.Exceptions import NoCardException
import time


class ACR122:
    def __init__(self, reader_index=0):
        available = readers()
        if not available:
            raise RuntimeError("No hay lectores disponibles.")
        if reader_index >= len(available):
            raise IndexError("Índice de lector fuera de rango.")
        self.reader = available[reader_index]
        self.conn = None

    def connect(self):
        """Siempre crea una conexión nueva."""
        if self.conn:
            try:
                self.conn.disconnect()
            except Exception:
                pass
        self.conn = self.reader.createConnection()
        self.conn.connect()  # lanza NoCardException si no hay tarjeta

    def disconnect(self):
        try:
            if self.conn:
                self.conn.disconnect()
        except Exception:
            pass
        self.conn = None

    def get_uid(self):
        GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
        if not self.conn:
            self.connect()
        data, sw1, sw2 = self.conn.transmit(GET_UID)
        if sw1 == 0x90 and sw2 == 0x00:
            uid_hex = ''.join(f'{b:02X}' for b in data)   # "04AABBCCDD"
            uid_spaced = ' '.join(f'{b:02X}' for b in data)
            return {
                "uid_hex": uid_hex,
                "uid_spaced": uid_spaced,
                "sw": f"{sw1:02X}{sw2:02X}"
            }
        else:
            raise RuntimeError(f"Error leyendo UID. SW={sw1:02X}{sw2:02X}")
