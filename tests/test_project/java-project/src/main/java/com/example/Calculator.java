package com.example;

/**
 * Simple calculator utility.
 */
public class Calculator {
    public static int add(int a, int b) {
        return a + b;
    }

    public static int subtract(int a, int b) {
        return a - b;
    }

    public static double divide(double a, double b) {
        if (b == 0) {
            throw new ArithmeticException("Division by zero");
        }
        return a / b;
    }

    public static String formatResult(String label, double value) {
        return String.format("%s: %.2f", label, value);
    }
}
