from itertools import product


def generate_names():
    """Generate a list of random `adjective + noun` strings."""
    adjectives = [
        'Exquisite',
        'Delicious',
        'Elegant',
        'Swanky',
        'Spicy',
        'Food Truck',
        'Artisanal',
        'Tasty',
    ]
    nouns = [
        'Sandwich',
        'Pizza',
        'Curry',
        'Pierogi',
        'Sushi',
        'Salad',
        'Stew',
        'Pasta',
        'Barbeque',
        'Bacon',
        'Pancake',
        'Waffle',
        'Chocolate',
        'Gyro',
        'Cookie',
        'Burrito',
        'Pie',
    ]
    return [' '.join(parts) for parts in product(adjectives, nouns)]
