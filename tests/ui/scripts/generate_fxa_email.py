import uuid


def create_fxa_email():
    id = uuid.uuid1()
    email = f"uitest-{id}@restmail.net"
    print(f"{email}")

if __name__ == "__main__":
    create_fxa_email()
