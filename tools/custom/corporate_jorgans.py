NAME = "corporate_jorgans"
DESC = "Fetches corporate Jorgans from web and converts them to Gujarati"
PARAMS = {"topic": ("string", "Corporate topic", True), "language": ("string", "Gujarati", True)}

def execute(args):
    # Fetch Jorgans from web
    jorgans = web_search({"query": "Jorgans corporate " + args["topic"]})

    # Convert Jorgans to Gujarati
    gujarati_jorgans = []
    for jorgan in jorgans:
        gujarati_jorgan = translate_text(jorgan, "en", "gu")
        gujarati_jorgans.append(gujarati_jorgan)

    # Write Jorgans to file
    file_path = "C:\\Users\\yagnesh\\Desktop\\file.txt"
    with open(file_path, "w") as file:
        for jorgan in gujarati_jorgans:
            file.write(jorgan + "\n")

    # Return success message
    return "File created successfully", None