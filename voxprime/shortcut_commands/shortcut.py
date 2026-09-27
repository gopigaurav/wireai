class ShortcutManager:
    def __init__(self):

        # define the shortcuts and their corresponding expansions
        self.shortcuts = {
            "time": "What is the current time? [get_current_time]",
        }

    def __call__(self, user_input):
        shortcut_key = user_input.lower()

        if shortcut_key.startswith("weather "):
            city = user_input[8:].strip()
            user_input = f"What's the weather in {city}? [get_weather(city=\"{city}\")]"
            return user_input
        return self.shortcuts.get(shortcut_key, user_input)

shortcut_manager = ShortcutManager()


def shortcuts(user_input):
    return shortcut_manager(user_input)