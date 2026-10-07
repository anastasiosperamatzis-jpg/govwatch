"""Bot Προθεσμιών: εντοπίζει προθεσμίες αιτήσεων/επιδομάτων στα νέα του seen.db και στέλνει υπενθυμίσεις."""
import re
import registry_db as R

KW = re.compile(r"προθεσμι|παραταση|ληγει|αιτησ|υποβολ|μεχρι|εως\b|ληξη")
NEAR = re.compile(r"προθεσμι\w*|παραταση\w*|ληγει|εως|μεχρι|ληξη")


def main():
    return R.scan_and_notify("deadlines", "deadline_date", "📅", "Προθεσμίες", KW, NEAR)


if __name__ == "__main__":
    print("προθεσμίες (νέες, ειδοποιήσεις):", main())
