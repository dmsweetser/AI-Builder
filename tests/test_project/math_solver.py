"""Calculate the sum of all prime numbers up to 100."""

def sieve_of_eratosthenes(limit):
    """Return a list of all prime numbers up to limit using the Sieve of Eratosthenes."""
    is_prime = [True] * (limit + 1)
    is_prime[0] = is_prime[1] = False
    
    for number in range(2, int(limit ** 0.5) + 1):
        if is_prime[number]:
            for multiple in range(number * number, limit + 1, number):
                is_prime[multiple] = False
    
    return [num for num in range(2, limit + 1) if is_prime[num]]

def main():
    limit = 100
    primes = sieve_of_eratosthenes(limit)
    total = sum(primes)
    
    print(f"Prime numbers up to {limit}:")
    print(primes)
    print(f"Count of primes: {len(primes)}")
    print(f"Sum of all primes up to {limit}: {total}")

if __name__ == "__main__":
    main()