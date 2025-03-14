from _typeshed import Incomplete

from .StreamDeck import ControlType as ControlType
from .StreamDeck import StreamDeck as StreamDeck

class StreamDeckOriginalV2(StreamDeck):
    KEY_COUNT: int
    KEY_COLS: int
    KEY_ROWS: int
    KEY_PIXEL_WIDTH: int
    KEY_PIXEL_HEIGHT: int
    KEY_IMAGE_FORMAT: str
    KEY_FLIP: Incomplete
    KEY_ROTATION: int
    DECK_TYPE: str
    DECK_VISUAL: bool
    IMAGE_REPORT_LENGTH: int
    IMAGE_REPORT_HEADER_LENGTH: int
    IMAGE_REPORT_PAYLOAD_LENGTH: Incomplete
    BLANK_KEY_IMAGE: Incomplete
    def reset(self) -> None: ...
    def set_brightness(self, percent) -> None: ...
    def get_serial_number(self): ...
    def get_firmware_version(self): ...
    def set_key_image(self, key, image) -> None: ...
    def set_touchscreen_image(self, image, x_pos: int = 0, y_pos: int = 0, width: int = 0, height: int = 0) -> None: ...
    def set_key_color(self, key, r, g, b) -> None: ...
    def set_screen_image(self, image) -> None: ...
