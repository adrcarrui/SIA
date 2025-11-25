from smartcard.scard import (
    SCardEstablishContext,
    SCardListReaders,
    SCardConnect,
    SCardDisconnect,
    SCardReleaseContext,
    SCARD_SCOPE_USER,
    SCARD_SHARE_DIRECT,
    SCARD_S_SUCCESS,
)
from smartcard.scard import SCARD_UNPOWER_CARD  # para Disconnect
from smartcard.scard import SCardControl, SCARD_CTL_CODE

class ACR122:
    """
    Conexión directa al lector ACR122U (modo SCARD_SHARE_DIRECT),
    NO a la tarjeta. No hace falta que haya tarjeta presente.
    """

    def __init__(self, reader_index: int = 0):
        self.hcontext = None
        self.hcard = None
        self.reader_name = None
        self.connect_direct(reader_index)

    def connect_direct(self, reader_index: int = 0):
        # 1) Crear contexto PC/SC
        hresult, hcontext = SCardEstablishContext(SCARD_SCOPE_USER)
        if hresult != SCARD_S_SUCCESS:
            raise RuntimeError(f"Error en SCardEstablishContext: 0x{hresult:08X}")
        self.hcontext = hcontext

        # 2) Listar lectores
        hresult, readers = SCardListReaders(self.hcontext, [])
        if hresult != SCARD_S_SUCCESS or not readers:
            raise RuntimeError("No se encontraron lectores PC/SC.")
        if reader_index < 0 or reader_index >= len(readers):
            raise IndexError(f"Índice de lector inválido: {reader_index}")

        self.reader_name = readers[reader_index]
        # print(f"Usando lector: {self.reader_name}")

        # 3) Conectar en modo DIRECTO (sin tarjeta)
        #
        #   - SCARD_SHARE_DIRECT → control directo del lector
        #   - protocolo = 0       → permitido sólo en modo DIRECT
        #
        hresult, hcard, dwActiveProtocol = SCardConnect(
            self.hcontext,
            self.reader_name,
            SCARD_SHARE_DIRECT,
            0,  # sin protocolo, estamos hablando con el lector, no con una tarjeta
        )
        if hresult != SCARD_S_SUCCESS:
            raise RuntimeError(f"Error en SCardConnect (DIRECT): 0x{hresult:08X}")

        self.hcard = hcard
        # dwActiveProtocol normalmente será "undefined" en DIRECT, es normal.

    def disconnect(self):
        if self.hcard is not None:
            try:
                SCardDisconnect(self.hcard, SCARD_UNPOWER_CARD)
            finally:
                self.hcard = None
        if self.hcontext is not None:
            try:
                SCardReleaseContext(self.hcontext)
            finally:
                self.hcontext = None

    def send_escape(self, payload):
        """
        payload: lista de enteros (0–255) o bytes/bytearray
        """
        control_code = SCARD_CTL_CODE(3500)  # típico para ACS en Windows

        in_buffer = list(payload)  # <-- lo que quiere pyscard

        hresult, response = SCardControl(self.hcard, control_code, in_buffer)
        if hresult != SCARD_S_SUCCESS:
            raise RuntimeError(f"Error en SCardControl: 0x{hresult:08X}")
        return response
                
if __name__== "__main__":
    nfc = ACR122()
    print(nfc.reader_name)

    red_error_apdu = [0xFF, 0x00, 0x40, 0x50, 0x04, 0x05, 0x05, 0x03, 0x00]
    nfc.send_escape(red_error_apdu)
