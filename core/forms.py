from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from . import permissions as perms
from .models import (ChatMessage, Comment, ExpenseClaim, FinanceEntry, Project, Submission, Task,
                     validate_private_files)

ACCEPT_ATTR = '.txt,.pdf,.doc,.docx,.xls,.xlsx,.md,.markdown,.png,.jpg,.jpeg,.gif,.webp,.bmp'


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """一次可选择多个附件的文件字段（Django 官方推荐写法）。"""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput(attrs={'multiple': True, 'accept': ACCEPT_ATTR}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            files = [single(item, initial) for item in data]
        else:
            files = [single(data, initial)]
        return validate_private_files(files)


class RoleLoginForm(AuthenticationForm):
    """登录表单：先选登录身份，再校验账号是否有这个身份。

    用户名一栏允许填用户名或邮箱；邮箱对应多个账号时要求改用用户名，避免登错人。
    """

    role = forms.ChoiceField(label='登录身份', choices=perms.LOGIN_ROLES,
                             widget=forms.RadioSelect(attrs={'class': 'role-radio'}))
    username = forms.CharField(label='用户名或邮箱', max_length=150,
                               widget=forms.TextInput(attrs={'autofocus': True, 'autocomplete': 'username'}))

    def clean_username(self):
        value = (self.cleaned_data.get('username') or '').strip()
        if User.objects.filter(username__iexact=value).exists():
            return value
        matches = list(User.objects.filter(email__iexact=value).values_list('username', flat=True))
        if len(matches) == 1:
            return matches[0]  # 用邮箱登录：换成真正的用户名再走认证。
        if len(matches) > 1:
            raise forms.ValidationError('该邮箱对应多个账号，请改用用户名登录。')
        return value  # 查不到就原样交给认证，由认证给出统一的失败提示。


class RegisterForm(UserCreationForm):
    invite_code = forms.CharField(label='邀请码', max_length=100, strip=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username',)
        labels = {'username': '账户名'}

    def clean_username(self):
        username = super().clean_username()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('账户名已被使用。')
        return username


class NormalUserRegisterForm(UserCreationForm):
    """普通用户自助注册：不需要邀请码，注册后只能看到展示、公共聊天室和关于页面。"""

    email = forms.EmailField(label='邮箱（可选，可用于登录）', required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')
        labels = {'username': '用户名'}

    def clean_username(self):
        username = super().clean_username()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('用户名已被使用。')
        return username

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('该邮箱已被使用，换一个或留空。')
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get('email') or ''
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
        return user


class ChatMessageForm(forms.ModelForm):
    class Meta:
        model = ChatMessage
        fields = ('body',)
        labels = {'body': ''}
        widgets = {'body': forms.Textarea(attrs={'rows': 2, 'maxlength': 2000,
                                                 'placeholder': '说点什么…（回车发送，Shift+回车换行）'})}


class ProfileForm(forms.ModelForm):
    """个人中心里由本人维护的资料：姓名与邮箱（邮箱用于接收团队通知）。"""

    class Meta:
        model = User
        fields = ('first_name', 'email')
        labels = {'first_name': '姓名（可选）', 'email': '邮箱（可选）'}
        widgets = {'email': forms.EmailInput(attrs={'autocomplete': 'email'})}


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ('name', 'goal', 'description', 'owner', 'members')
        labels = {'name': '项目名称', 'goal': '项目目标', 'description': '项目说明（可选）',
                  'owner': '项目负责人', 'members': '项目成员'}
        widgets = {'goal': forms.Textarea(attrs={'rows': 3}),
                   'description': forms.Textarea(attrs={'rows': 3}),
                   'members': forms.SelectMultiple(attrs={'size': 8})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['owner'].queryset = User.objects.filter(is_active=True).order_by('username')
        self.fields['members'].queryset = User.objects.filter(is_active=True, is_staff=False).order_by('username')
        self.fields['members'].required = False

    def save(self, commit=True):
        project = super().save(commit=commit)
        if commit:
            project.members.remove(project.owner)  # 负责人不必重复出现在成员列表里。
        return project


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ('title', 'description', 'assignee', 'due_date')
        labels = {'title': '任务名称', 'description': '任务说明', 'assignee': '任务负责人', 'due_date': '截止日期'}
        widgets = {'description': forms.Textarea(attrs={'rows': 5}),
                   'due_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})}

    def __init__(self, *args, project=None, parent=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project or getattr(self.instance, 'project', None)
        self.parent = parent if parent is not None else getattr(self.instance, 'parent', None)
        if self.project is not None:
            self.fields['assignee'].queryset = User.objects.filter(
                pk__in=self.project.participant_ids, is_active=True).order_by('username')
        else:
            self.fields['assignee'].queryset = User.objects.filter(is_active=True, is_staff=False).order_by('username')

    def save(self, commit=True):
        task = super().save(commit=False)
        if self.project is not None:
            task.project = self.project
        if self.parent is not None:
            task.parent = self.parent
        if commit:
            task.save()
        return task


class ProgressForm(forms.Form):
    progress = forms.IntegerField(label='完成进度（0-99）', min_value=0, max_value=99)


class SubmissionForm(forms.ModelForm):
    attachments = MultipleFileField(label='附件（可选，可多选）', required=False,
                                    help_text='支持 TXT、PDF、Word、Excel、Markdown 和图片，单个不超过 20 MB。')

    class Meta:
        model = Submission
        fields = ('summary',)
        labels = {'summary': '成果内容（可直接写文字，不必上传附件）'}
        widgets = {'summary': forms.Textarea(attrs={'rows': 6})}


class CommentForm(forms.ModelForm):
    attachments = MultipleFileField(label='附件（可选，可多选）', required=False)

    class Meta:
        model = Comment
        fields = ('kind', 'body')
        labels = {'kind': '类型', 'body': '内容'}
        widgets = {'body': forms.Textarea(attrs={'rows': 3, 'placeholder': '目标、思路、问题或结论…'})}


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(label='审核决定', choices=[('accept', '通过'), ('reject', '退回修改')])
    note = forms.CharField(label='审核结论', max_length=3000, required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def clean(self):
        data = super().clean()
        if data.get('decision') == 'reject' and not (data.get('note') or '').strip():
            self.add_error('note', '退回时请填写原因。')
        return data


class FinalForm(forms.Form):
    note = forms.CharField(label='选用说明（可选）', max_length=1000, required=False,
                           widget=forms.Textarea(attrs={'rows': 2}))


class FinanceForm(forms.ModelForm):
    attachments = MultipleFileField(label='凭证（可选，可多选）', required=False)

    class Meta:
        model = FinanceEntry
        fields = ('kind', 'amount', 'occurred_on', 'memo')
        labels = {'kind': '类型', 'amount': '金额（元）', 'occurred_on': '发生日期', 'memo': '说明'}
        widgets = {'occurred_on': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
                   'memo': forms.Textarea(attrs={'rows': 4})}


class ClaimForm(forms.ModelForm):
    attachments = MultipleFileField(label='发票等凭证（可选，可多选）', required=False)

    class Meta:
        model = ExpenseClaim
        fields = ('amount', 'occurred_on', 'memo')
        labels = {'amount': '申请金额（元）', 'occurred_on': '发生日期', 'memo': '事由'}
        widgets = {'occurred_on': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
                   'memo': forms.Textarea(attrs={'rows': 4})}
