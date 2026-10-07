"""Τρέχει όλα τα bots του registry με τη σειρά (για το workflow)."""
import dedupe, bot_prothesmies, bot_pliromes, bot_allages

if __name__ == "__main__":
    print("topics:", dedupe.build_topics())
    for name, mod in (("προθεσμίες", bot_prothesmies), ("πληρωμές", bot_pliromes), ("αλλαγές", bot_allages)):
        try:
            print(name, mod.main())
        except Exception as e:  # ένα bot που σπάει δεν ρίχνει τα υπόλοιπα
            print(f"[{name}] σφάλμα: {e}")
