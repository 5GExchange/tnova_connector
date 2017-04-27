import logging

# Additional logging level
VERBOSE = 5
# Add logger level to the log entries in test mode
FILE_LOGGER_FORMAT = "|%(levelname)s" \
                     "|%(name)s" \
                     "|%(asctime)s" \
                     "|---|%(message)s"
# Log file name
LOG_FILE = "log/connector.log"


class ColoredLogger(logging.Logger):
  """
  Main Logger class for coloured logging.

  Usage:

  """

  class ColorFormatter(logging.Formatter):
    """
    Main Formatter class for implementing the coloured message formatting.
    """
    # Line format
    # FORMAT = ("[$BOLD%(name)-20s$RESET][%(levelname)-18s]  "
    #           "%(message)s "
    #           "($BOLD%(filename)s$RESET:%(lineno)d)")
    # FORMAT = logging.BASIC_FORMAT
    # FORMAT = "[$BOLD%(name)-15s$RESET][%(levelname)-18s] %(message)s"
    FORMAT = "[$BOLD%(levelname)-15s$RESET][$BOLD%(name)-18s$RESET] %(" \
             "message)s"

    # Colouring constants
    BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)
    RESET_SEQ = "\033[0m"
    COLOR_SEQ = "\033[1;%dm"
    BOLD_SEQ = "\033[1m"
    # Level - color binding
    COLORS = {
      'VERBOSE': WHITE,
      'DEBUG': CYAN,
      'INFO': GREEN,
      'WARNING': YELLOW,
      'ERROR': RED,
      'CRITICAL': RED,
    }

    def __init__ (self, use_color=True):
      msg = self.formatter_msg(self.FORMAT, use_color)
      logging.Formatter.__init__(self, msg)
      self.use_color = use_color

    def formatter_msg (self, msg, use_color=True):
      if use_color:
        msg = msg.replace("$RESET", self.RESET_SEQ).replace("$BOLD",
                                                            self.BOLD_SEQ)
      else:
        msg = msg.replace("$RESET", "").replace("$BOLD", "")
      return msg

    def format (self, record):
      levelname = record.levelname
      if self.use_color and levelname in self.COLORS:
        fore_color = 30 + self.COLORS[levelname]
        levelname_color = self.COLOR_SEQ % fore_color + levelname + \
                          self.RESET_SEQ
        record.levelname = levelname_color
      return logging.Formatter.format(self, record)

  def __init__ (self, name):
    # Configure the logger internally
    logging.Logger.__init__(self, name)
    self.propagate = False
    hndlr = logging.StreamHandler()
    hndlr.setFormatter(self.ColorFormatter())
    self.addHandler(hndlr)
    return

  @classmethod
  def createHandler (cls):
    handler = logging.StreamHandler()
    handler.setFormatter(cls.ColorFormatter())
    return handler

  @staticmethod
  def configure (name=None, level=logging.INFO):
    import logging
    # logging.getLogger().addHandler(NullHandler())
    logging.setLoggerClass(ColoredLogger)
    logging.basicConfig(level=level)
    log = logging.getLogger(name if name is not None else '__main__')
    # log.setLevel(level)
    return log


def setup_flask_logging (app, log_file=LOG_FILE):
  # Configure root logging
  logging.addLevelName(VERBOSE, 'VERBOSE')
  log = logging.getLogger()
  # Configure a DEBUG level logger for initialization
  log.setLevel(logging.DEBUG)
  # Add file logger first to avoid magic chars in log file
  hdlr = logging.FileHandler(filename=log_file, mode='w')
  hdlr.setFormatter(fmt=logging.Formatter(fmt=FILE_LOGGER_FORMAT))
  log.addHandler(hdlr=hdlr)
  # Add colored console logging
  log.addHandler(ColoredLogger.createHandler())
  # Adjust Flask logging to common logging
  app.logger.handlers[:] = [hdlr, ColoredLogger.createHandler()]
  app.logger.propagate = False
  app.logger.setLevel(log.getEffectiveLevel())
  return log
