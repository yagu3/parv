NAME = "random_joke"
DESC = "Picks a random joke from a list of 10 hardcoded jokes"
PARAMS = {}

def execute(args):
    jokes = ["Why don't scientists trust atoms? Because they make up everything.",
             "Why don't eggs tell jokes? They'd crack each other up.",
             "Why did the tomato turn red? Because it saw the salad dressing.",
             "What do you call a fake noodle? An impasta.",
             "Why did the scarecrow win an award? Because he was outstanding in his field.",
             "Why did the bicycle fall over? Because it was two-tired.",
             "What do you call a group of cows playing instruments? A moo-sical band.",
             "Why did the chicken cross the playground? To get to the other slide.",
             "What do you call a bear with no socks on? Barefoot.",
             "Why did the banana go to the doctor? He wasn't peeling well."]
    import random
    return random.choice(jokes), None