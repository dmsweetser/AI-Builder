def transform_word(s):
    # Reverse the string
    reversed_str = s[::-1]
    # Convert to uppercase
    upper_str = reversed_str.upper()
    # Remove all vowels
    vowels = set('AEIOUaeiou')
    result = ''.join(char for char in upper_str if char not in vowels)
    return result

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        input_str = ' '.join(sys.argv[1:])
    else:
        input_str = "Hello World"
    
    result = transform_word(input_str)
    print(f"Input:    {input_str}")
    print(f"Reversed: {input_str[::-1]}")
    print(f"Uppercase: {input_str[::-1].upper()}")
    print(f"Result:   {result}")