import logging
from colorama import init
init()
# Example usage:
DEBUG = 'INFO'  # This can be changed to ERROR, WARN, INFO, DEBUG, CRITICAL, TRACE
FUNC_ACRONYM_MAP = {
    'on_ready': 'READY',
    'background_search_marketplace': 'BGSEA',
    'get_listing_info': 'GETLI',
    'received_message': 'RECIV',
    'log_message': 'SENDM',
    # Add other mappings as needed
}

class ANSIColors:
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[97m'
    RESET = '\033[0m'


# Custom formatter with color support
class CustomFormatter(logging.Formatter):
    COLOR_MAP = {
        logging.ERROR: ANSIColors.RED,
        logging.WARNING: ANSIColors.YELLOW,
        logging.INFO: ANSIColors.WHITE,
        logging.DEBUG: ANSIColors.BLUE,
        logging.CRITICAL: ANSIColors.MAGENTA,
    }

    def format(self, record):
        func_name = record.funcName
        # Look up the function name acronym in the mapping or use the first 5 letters of the function name
        func_acronym = FUNC_ACRONYM_MAP.get(func_name, func_name[:5].upper())
        # Check if 'indent' was passed in extra and set the prefix accordingly
        if getattr(record, 'indent', False):
            prefix = '\t'
            fmt = '   %(message)s'
        else:
            prefix = ''
            fmt = f'[%(levelname)s|{func_acronym}] %(message)s'

        # Set the format dynamically based on the presence of 'indent'
        self._style._fmt = fmt

        color = self.COLOR_MAP.get(record.levelno, ANSIColors.WHITE)
        message = super().format(record)
        message = f"{prefix}{color}{message}{ANSIColors.RESET}"
        return message


# Set up logging configuration
logger = logging.getLogger()
logger.setLevel(DEBUG)

# Create console handler with custom formatter
console_handler = logging.StreamHandler()
console_handler.setFormatter(CustomFormatter())
logger.addHandler(console_handler)

# Example usage
# logging.error("This is an error message.")  # RED
# logging.warning("This is a warning message.")  # YELLOW
# logging.info("This is an info message.")  # GREY
# logging.debug("This is a debug message.")  # BLUE
# logging.critical("This is a critical message.")  # PURPLE
