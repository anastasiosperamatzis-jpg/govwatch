"""Bot Πληρωμών: εντοπίζει ημερομηνίες πληρωμής επιδομάτων/συντάξεων στα νέα του seen.db."""
import re
import registry_db as R

KW = re.compile(r"πληρωμ|καταβαλλ|πιστωνεται|πιστωση|πληρωνεται|πληρωνονται|καταβολη")


def main():
    return R.scan_and_notify("payments", "pay_date", "💶", "Πληρωμές", KW)


if __name__ == "__main__":
    print("πληρωμές (νέες, ειδοποιήσεις):", main())
