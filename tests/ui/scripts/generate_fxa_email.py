import uuid


def create_fxa_email():
    print(f"uitest-{uuid.uuid1()}@restmail.net")


if __name__ == "__main__":
    create_fxa_email()
