from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import CustomUser

class CustomUserCreationForm(UserCreationForm):
    first_name = forms.CharField(max_length=30, required=False, help_text='Optional.')
    last_name = forms.CharField(max_length=150, required=False, help_text='Optional.')
    email = forms.EmailField(required=True, help_text='Required. Enter a valid email address.')
    phone_number = forms.CharField(max_length=15, required=False, help_text='Optional. e.g., +919876543210')
    date_of_birth = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), required=False)
    gender = forms.ChoiceField(choices=CustomUser.GENDER_CHOICES, required=False)
    address = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)
    profile_picture = forms.ImageField(required=False)

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = UserCreationForm.Meta.fields + (
            'first_name', 'last_name', 'email', 'phone_number',
            'date_of_birth', 'gender', 'address', 'profile_picture'
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True

class CustomUserChangeForm(UserChangeForm):
    """
    A form for updating user profiles, based on the CustomUser model.
    It includes all the custom fields added to the user model.
    """
    class Meta(UserChangeForm.Meta):
        model = CustomUser
        # Exclude the password field from the profile update form.
        exclude = ('password',)
        # Explicitly list all fields that should be editable on the profile page.
        fields = (
            'username', 'first_name', 'last_name', 'email', 'phone_number',
            'date_of_birth', 'gender', 'address', 'profile_picture'
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ensure email is set as required
        self.fields['email'].required = True

        # Custom styling attributes for the widgets
        self.fields['username'].widget.attrs.update({
            'class': 'input-custom',
            'placeholder': 'Enter a username',
            'readonly': 'readonly' # To prevent editing the username
        })
        self.fields['first_name'].widget.attrs.update({
            'class': 'input-custom',
            'placeholder': 'Enter your first name'
        })
        self.fields['last_name'].widget.attrs.update({
            'class': 'input-custom',
            'placeholder': 'Enter your last name'
        })
        self.fields['email'].widget.attrs.update({
            'class': 'input-custom',
            'placeholder': 'Enter your email address'
        })
        self.fields['phone_number'].widget.attrs.update({
            'class': 'input-custom',
            'placeholder': 'e.g., +919876543210'
        })
        self.fields['date_of_birth'].widget.attrs.update({
            'class': 'input-custom',
            'placeholder': 'DD-MM-YYYY'
        })
        self.fields['gender'].widget.attrs.update({
            'class': 'input-custom select-custom'
        })
        self.fields['address'].widget.attrs.update({
            'class': 'input-custom',
            'placeholder': 'Enter your address'
        })
        # The file input is styled separately in the HTML
        self.fields['profile_picture'].widget.attrs.update({
            'class': 'form-control-file'
        })
