from smartcard.System import readers
from smartcard.Exceptions import NoCardException
import time

# 🔽 IMPORTS EXTRA PARA ESCAPE / DIRECT
from smartcard.scard import (
    SCardEstablishContext,
    SCardListReaders,
    SCardConnect,
    SCardDisconnect,
    SCardReleaseContext,
    SCardControl,
    SCARD_SCOPE_USER,
    SCARD_SHARE_DIRECT,
    SCARD_S_SUCCESS,
    SCARD_UNPOWER_CARD,
    SCARD_CTL_CODE,
)


class ACR122:
    def __init__(self, reader_index=0):
        available = readers()
        if not available:
            raise RuntimeError("No readers available.")
        if reader_index >= len(available):
            raise IndexError("Reader index out of range.")
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
            raise RuntimeError(f"Error reading UID. SW={sw1:02X}{sw2:02X}")


# ================== FUNCIÓN EXTRA: SILENCIAR BUZZER ==================

def init_buzzer_off(reader_index: int = 0):
    """
    Llamar UNA VEZ al iniciar la app para desactivar el buzzer del ACR122U
    en la detección de tarjeta.

    No usa la clase ACR122, va directo por PC/SC (modo DIRECT).
    """
    # 1) Contexto PC/SC
    hresult, hcontext = SCardEstablishContext(SCARD_SCOPE_USER)
    if hresult != SCARD_S_SUCCESS:
        raise RuntimeError(f"SCardEstablishContext failed: 0x{hresult:08X}")

    try:
        # 2) Listar lectores
        hresult, rdrs = SCardListReaders(hcontext, [])
        if hresult != SCARD_S_SUCCESS or not rdrs:
            raise RuntimeError("No PC/SC readers found.")
        if reader_index < 0 or reader_index >= len(rdrs):
            raise IndexError(f"Invalid reader index: {reader_index}")

        reader_name = rdrs[reader_index]

        # 3) Conectar en DIRECT (lector, no tarjeta)
        hresult, hcard, active_proto = SCardConnect(
            hcontext,
            reader_name,
            SCARD_SHARE_DIRECT,
            0,   # protocolo=0 en DIRECT
        )
        if hresult != SCARD_S_SUCCESS:
            raise RuntimeError(f"SCardConnect(DIRECT) failed: 0x{hresult:08X}")

        try:
            # 4) EscapeCommand → Set Buzzer Output for Card Detection
            #    FF 00 52 P2 00
            #    P2 = 00h → buzzer OFF para cualquier estado (según doc ACS)
            control_code = SCARD_CTL_CODE(3500)
            apdu_buzzer_off = [0xFF, 0x00, 0x52, 0x00, 0x00]

            hresult, response = SCardControl(hcard, control_code, apdu_buzzer_off)
            if hresult != SCARD_S_SUCCESS:
                raise RuntimeError(f"SCardControl(buzzer_off) failed: 0x{hresult:08X}")

            # Si quieres mirar la respuesta:
            # print("Buzzer OFF response:", response)

        finally:
            SCardDisconnect(hcard, SCARD_UNPOWER_CARD)

    finally:
        SCardReleaseContext(hcontext)
