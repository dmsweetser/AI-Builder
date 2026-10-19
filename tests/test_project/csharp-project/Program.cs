using System;
using System.Collections.Generic;

namespace CSharpProject
{
    /// <summary>
    /// Main application class.
    /// </summary>
    public class Program
    {
        public static void Main(string[] args)
        {
            var calculator = new Calculator();
            Console.WriteLine($"2 + 3 = {calculator.Add(2, 3)}");
            Console.WriteLine($"10 - 4 = {calculator.Subtract(10, 4)}");
            Console.WriteLine($"5 * 6 = {calculator.Multiply(5, 6)}");
            
            var greeting = new Greeter();
            Console.WriteLine(greeting.SayHello("World"));
        }
    }

    /// <summary>
    /// Calculator utility class.
    /// </summary>
    public class Calculator
    {
        public int Add(int a, int b) => a + b;
        public int Subtract(int a, int b) => a - b;
        public int Multiply(int a, int b) => a * b;
        public double Divide(double a, double b)
        {
            if (b == 0) throw new DivideByZeroException();
            return a / b;
        }
    }

    /// <summary>
    /// Greeting utility.
    /// </summary>
    public class Greeter
    {
        public string SayHello(string name) => $"Hello, {name}!";
    }
}
