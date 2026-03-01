NAME  = "random_joke"
DESC  = "Tells a random joke"
PARAMS  = {"topic": ("string", "Joke topic", True)}

def execute(args):
    import random
    with open("jokes.txt", "r") as f:
        jokes = f.read().splitlines()
    return random.choice(jokes), None